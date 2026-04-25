"""Narrow GitHub client for automation pull request management."""

from __future__ import annotations

from typing import Any

import httpx

from planning_validator.models import AutomationPullRequest


class GitHubPullRequestError(RuntimeError):
    """Raised when GitHub PR management fails."""


class GitHubPullRequestClient:
    """Create and update the fixed planning-validator pull request."""

    def __init__(
        self,
        *,
        owner: str,
        repo: str,
        token: str,
        base_url: str = "https://api.github.com",
        timeout: float = 10.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.owner = owner
        self.repo = repo
        self._client = httpx.Client(
            base_url=f"{base_url.rstrip('/')}/",
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            timeout=timeout,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> GitHubPullRequestClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def find_open_pull_request(self, *, head_branch: str) -> AutomationPullRequest | None:
        payload = self._get_json_list(
            f"repos/{self.owner}/{self.repo}/pulls",
            params={"state": "open", "head": f"{self.owner}:{head_branch}"},
        )
        if not payload:
            return None
        first = payload[0]
        if not isinstance(first, dict):
            raise GitHubPullRequestError("GitHub pull request payload must be an object")
        return self._normalize_pull_request(first)

    def create_pull_request(
        self,
        *,
        title: str,
        body: str,
        head_branch: str,
        base_branch: str,
        draft: bool,
    ) -> AutomationPullRequest:
        payload = self._post_json(
            f"repos/{self.owner}/{self.repo}/pulls",
            json={
                "title": title,
                "body": body,
                "head": head_branch,
                "base": base_branch,
                "draft": draft,
            },
        )
        if not isinstance(payload, dict):
            raise GitHubPullRequestError("GitHub create pull request returned non-object payload")
        return self._normalize_pull_request(payload)

    def update_pull_request(self, *, number: int, title: str, body: str) -> AutomationPullRequest:
        payload = self._patch_json(
            f"repos/{self.owner}/{self.repo}/pulls/{number}",
            json={"title": title, "body": body},
        )
        if not isinstance(payload, dict):
            raise GitHubPullRequestError("GitHub update pull request returned non-object payload")
        return self._normalize_pull_request(payload)

    def add_labels(self, *, number: int, labels: list[str]) -> None:
        if not labels:
            return
        self._post_json(
            f"repos/{self.owner}/{self.repo}/issues/{number}/labels",
            json={"labels": labels},
        )

    def request_reviewers(self, *, number: int, reviewers: list[str]) -> None:
        if not reviewers:
            return
        self._post_json(
            f"repos/{self.owner}/{self.repo}/pulls/{number}/requested_reviewers",
            json={"reviewers": reviewers},
        )

    def _get_json_list(
        self,
        path: str,
        *,
        params: dict[str, object] | None = None,
    ) -> list[Any]:
        payload = self._request_json("GET", path, params=params)
        if not isinstance(payload, list):
            raise GitHubPullRequestError(
                f"GitHub API list request returned non-list payload for {path}"
            )
        return payload

    def _post_json(self, path: str, *, json: dict[str, object]) -> Any:
        return self._request_json("POST", path, json=json)

    def _patch_json(self, path: str, *, json: dict[str, object]) -> Any:
        return self._request_json("PATCH", path, json=json)

    def _request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, object] | None = None,
        json: dict[str, object] | None = None,
    ) -> Any:
        try:
            response = self._client.request(method, path, params=params, json=json)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GitHubPullRequestError(
                f"GitHub API request failed for {method} {path}: {exc}"
            ) from exc
        try:
            return response.json()
        except ValueError as exc:
            raise GitHubPullRequestError(
                f"GitHub API returned invalid JSON for {method} {path} "
                f"(status {response.status_code})"
            ) from exc

    def _normalize_pull_request(self, payload: dict[str, Any]) -> AutomationPullRequest:
        head = payload.get("head")
        base = payload.get("base")
        if not isinstance(head, dict) or not isinstance(base, dict):
            raise GitHubPullRequestError("GitHub pull request payload is missing head/base")
        return AutomationPullRequest.model_validate(
            {
                "number": payload["number"],
                "title": payload["title"],
                "url": payload["html_url"],
                "head_branch": head["ref"],
                "base_branch": base["ref"],
                "draft": bool(payload.get("draft", False)),
            }
        )
