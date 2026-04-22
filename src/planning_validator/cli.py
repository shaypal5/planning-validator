"""CLI entrypoint for planning-validator."""

from __future__ import annotations

import json
import os
from pathlib import Path

import typer

from planning_validator.config import ConfigError, load_config
from planning_validator.detector import run_detector
from planning_validator.github_api import GitHubApiError, GitHubEvidenceClient
from planning_validator.repo_snapshot import collect_recent_pr_snapshot, collect_repo_metadata

app = typer.Typer(
    add_completion=False,
    no_args_is_help=True,
    help="Validate and refresh planning and tracking documentation from repository evidence.",
)
CONFIG_OPTION = typer.Option(..., "--config", exists=True, dir_okay=False, readable=True)
REPO_ROOT_OPTION = typer.Option(
    None,
    "--repo-root",
    exists=True,
    file_okay=False,
    readable=True,
    resolve_path=True,
    help="Repository root used when expanding planning/tracking globs.",
)
JSON_OPTION = typer.Option(False, "--json", help="Emit machine-readable validation output.")
JSON_OUT_OPTION = typer.Option(
    ...,
    "--json-out",
    dir_okay=False,
    writable=True,
    resolve_path=True,
    help="Path where the detection JSON artifact will be written.",
)


def _not_implemented(command_name: str) -> None:
    typer.echo(f"'{command_name}' is reserved for a later milestone.", err=True)
    raise typer.Exit(code=1)


@app.command("validate-config")
def validate_config(
    config: Path = CONFIG_OPTION,
    repo_root: Path | None = REPO_ROOT_OPTION,
    as_json: bool = JSON_OPTION,
) -> None:
    """Parse and validate the target repository config."""

    try:
        resolved = load_config(config, repo_root=repo_root or Path.cwd())
    except ConfigError as exc:
        if as_json:
            typer.echo(json.dumps({"ok": False, "error": str(exc)}, indent=2))
        else:
            typer.echo(f"Config validation failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    payload = {
        "ok": True,
        "config_path": str(resolved.config_path),
        "repo_root": str(resolved.repo_root),
        "planning_files": list(resolved.planning_paths),
        "tracking_files": list(resolved.tracking_paths),
        "patchable_files": list(resolved.patchable_paths),
    }
    if as_json:
        typer.echo(json.dumps(payload, indent=2))
        return

    typer.echo(
        "Config is valid.\n"
        f"Planning files: {len(resolved.planning_paths)}\n"
        f"Tracking files: {len(resolved.tracking_paths)}\n"
        f"Resolved document set: {len(resolved.all_document_paths)}",
    )


@app.command()
def detect(
    config: Path = CONFIG_OPTION,
    repo_root: Path | None = REPO_ROOT_OPTION,
    json_out: Path = JSON_OUT_OPTION,
) -> None:
    """Detect stale planning and tracking documentation from repository evidence."""

    root = repo_root or Path.cwd()
    try:
        resolved = load_config(config, repo_root=root)
        metadata = collect_repo_metadata(resolved.repo_root)
        token = os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN environment variable is required for detect.")

        owner, repo_name = metadata.repo.split("/", maxsplit=1)
        with GitHubEvidenceClient(owner=owner, repo=repo_name, token=token) as github_client:
            snapshot = collect_recent_pr_snapshot(
                resolved,
                github_client=github_client,
                repo=metadata.repo,
                default_branch=metadata.default_branch,
                head_sha=metadata.head_sha,
            )

        detection_result = run_detector(resolved, snapshot)
        json_out.parent.mkdir(parents=True, exist_ok=True)
        json_out.write_text(
            detection_result.model_dump_json(indent=2),
            encoding="utf-8",
        )
    except (ConfigError, GitHubApiError, OSError, RuntimeError, ValueError) as exc:
        typer.echo(f"Detection failed: {exc}", err=True)
        raise typer.Exit(code=1) from exc

    typer.echo(detection_result.summary)


@app.command()
def patch() -> None:
    """Reserved for Milestone 4."""

    _not_implemented("patch")


@app.command()
def run() -> None:
    """Reserved for Milestone 6."""

    _not_implemented("run")


if __name__ == "__main__":
    app()
