"""Git branch and commit operations for automation PR updates."""

from __future__ import annotations

import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from planning_validator.models import ValidatedPatch


class GitCommandError(RuntimeError):
    """Raised when a git command fails."""


class GitRunResult(BaseModel):
    stdout: str = ""
    stderr: str = ""
    returncode: int = 0

    model_config = ConfigDict(extra="forbid")


class GitRunner(Protocol):
    def run(
        self,
        repo_root: Path,
        args: Sequence[str],
        *,
        check: bool = True,
    ) -> GitRunResult:
        """Run a git command in repo_root."""


class SubprocessGitRunner:
    """Run git commands via the standard library subprocess module."""

    def run(
        self,
        repo_root: Path,
        args: Sequence[str],
        *,
        check: bool = True,
    ) -> GitRunResult:
        completed = subprocess.run(
            ["git", *args],
            cwd=repo_root,
            check=False,
            capture_output=True,
            text=True,
        )
        result = GitRunResult(
            stdout=completed.stdout,
            stderr=completed.stderr,
            returncode=completed.returncode,
        )
        if check and result.returncode != 0:
            command = "git " + " ".join(args)
            detail = result.stderr.strip() or result.stdout.strip()
            raise GitCommandError(f"{command} failed: {detail}")
        return result


class BranchManager:
    """Prepare the fixed automation branch and commit validated patch edits."""

    def __init__(
        self,
        *,
        repo_root: Path,
        runner: GitRunner | None = None,
    ) -> None:
        self.repo_root = repo_root
        self.runner = runner or SubprocessGitRunner()

    def prepare_branch(self, *, base_branch: str, automation_branch: str) -> None:
        self.runner.run(self.repo_root, ["fetch", "origin"])
        if self._remote_branch_exists(automation_branch):
            if self._local_branch_exists(automation_branch):
                self.runner.run(self.repo_root, ["switch", automation_branch])
            else:
                self.runner.run(
                    self.repo_root,
                    ["switch", "-c", automation_branch, "--track", f"origin/{automation_branch}"],
                )
            self.runner.run(self.repo_root, ["pull", "--ff-only", "origin", automation_branch])
            return

        if self._local_branch_exists(automation_branch):
            self.runner.run(self.repo_root, ["switch", automation_branch])
            return

        self.runner.run(
            self.repo_root,
            ["switch", "-c", automation_branch, f"origin/{base_branch}"],
        )

    def commit_validated_patch(self, patch: ValidatedPatch, *, commit_message: str) -> bool:
        if not patch.edits:
            return False

        paths = [edit.path for edit in patch.edits]
        self.runner.run(self.repo_root, ["add", "--", *paths])
        if not self.has_staged_changes(paths=paths):
            return False

        self.runner.run(self.repo_root, ["commit", "-m", commit_message, "--", *paths])
        return True

    def has_staged_changes(self, *, paths: Sequence[str] | None = None) -> bool:
        args = ["diff", "--cached", "--quiet"]
        if paths:
            args.extend(["--", *paths])
        result = self.runner.run(
            self.repo_root,
            args,
            check=False,
        )
        if result.returncode == 0:
            return False
        if result.returncode == 1:
            return True
        detail = result.stderr.strip() or result.stdout.strip()
        raise GitCommandError(f"git diff --cached --quiet failed: {detail}")

    def push_branch(self, branch: str) -> None:
        self.runner.run(self.repo_root, ["push", "--set-upstream", "origin", branch])

    def _local_branch_exists(self, branch: str) -> bool:
        return (
            self.runner.run(
                self.repo_root,
                ["rev-parse", "--verify", f"refs/heads/{branch}"],
                check=False,
            ).returncode
            == 0
        )

    def _remote_branch_exists(self, branch: str) -> bool:
        return (
            self.runner.run(
                self.repo_root,
                ["rev-parse", "--verify", f"refs/remotes/origin/{branch}"],
                check=False,
            ).returncode
            == 0
        )
