"""GitHub evidence collection for recent merged pull requests and linked issues."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

import httpx

from planning_validator.models import GitHubIssueState, RecentIssue, RecentPullRequest

_LINKED_ISSUE_PATTERN = re.compile(
    r"\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)\s+#(?P<number>\d+)\b",
    re.IGNORECASE,
)


class GitHubApiError(RuntimeError):
    """Raised when GitHub evidence collection fails."""


class GitHubEvidenceClient:
    """Fetch recent merged pull requests and linked issues from GitHub."""

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

    def __enter__(self) -> GitHubEvidenceClient:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def fetch_recent_merged_pull_requests(
        self,
        *,
        merged_since: datetime,
        include_file_lists: bool = False,
        include_linked_issues: bool = False,
    ) -> list[RecentPullRequest]:
        if merged_since.tzinfo is None or merged_since.utcoffset() is None:
            raise ValueError("merged_since must include timezone info")

        pull_requests: list[RecentPullRequest] = []
        for payload in self._paginate(
            f"repos/{self.owner}/{self.repo}/pulls",
            params={"state": "closed", "sort": "updated", "direction": "desc"},
        ):
            if not isinstance(payload, dict):
                raise GitHubApiError("GitHub pull request payload must be an object")
            if payload.get("merged_at") is None:
                continue

            pull_request = self._normalize_pull_request(payload)
            if pull_request.merged_at < merged_since:
                continue

            if include_file_lists:
                pull_request = pull_request.model_copy(
                    update={"changed_files": self._fetch_pull_request_files(pull_request.number)}
                )
            if include_linked_issues:
                pull_request = pull_request.model_copy(
                    update={"linked_issues": self._fetch_linked_issues(pull_request.body)}
                )

            pull_requests.append(pull_request)

        pull_requests.sort(key=lambda pull_request: pull_request.merged_at, reverse=True)
        return pull_requests

    def _fetch_pull_request_files(self, pull_request_number: int) -> list[str]:
        changed_files: list[str] = []
        for payload in self._paginate(
            f"repos/{self.owner}/{self.repo}/pulls/{pull_request_number}/files"
        ):
            if not isinstance(payload, dict):
                raise GitHubApiError("GitHub pull request file payload must be an object")

            filename = payload.get("filename")
            if isinstance(filename, str) and filename:
                changed_files.append(filename)

        return changed_files

    def _fetch_linked_issues(self, body: str | None) -> list[RecentIssue]:
        linked_issues: list[RecentIssue] = []
        seen_numbers: set[int] = set()
        for issue_number in self._extract_linked_issue_numbers(body):
            if issue_number in seen_numbers:
                continue

            issue = self._fetch_issue(issue_number)
            if issue is None:
                continue

            seen_numbers.add(issue_number)
            linked_issues.append(issue)

        return linked_issues

    def _fetch_issue(self, issue_number: int) -> RecentIssue | None:
        payload = self._get_json(f"repos/{self.owner}/{self.repo}/issues/{issue_number}")
        if not isinstance(payload, dict):
            raise GitHubApiError("GitHub issue payload must be an object")
        if "pull_request" in payload:
            return None
        return self._normalize_issue(payload)

    def _paginate(self, path: str, *, params: dict[str, object] | None = None) -> list[Any]:
        items: list[Any] = []
        page = 1
        while True:
            page_items = self._get_json_list(
                path,
                params={
                    "per_page": 100,
                    "page": page,
                    **(params or {}),
                },
            )
            if not page_items:
                break
            items.extend(page_items)
            if len(page_items) < 100:
                break
            page += 1
        return items

    def _get_json(self, path: str, *, params: dict[str, object] | None = None) -> Any:
        try:
            response = self._client.get(path, params=params)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise GitHubApiError(f"GitHub API request failed for {path}: {exc}") from exc
        return response.json()

    def _get_json_list(self, path: str, *, params: dict[str, object] | None = None) -> list[Any]:
        payload = self._get_json(path, params=params)
        if not isinstance(payload, list):
            raise GitHubApiError(f"GitHub API list request returned non-list payload for {path}")
        return payload

    def _normalize_pull_request(self, payload: dict[str, Any]) -> RecentPullRequest:
        labels = [
            label["name"]
            for label in payload.get("labels", [])
            if isinstance(label, dict) and isinstance(label.get("name"), str)
        ]
        user = payload.get("user")
        author = user.get("login") if isinstance(user, dict) else None
        return RecentPullRequest.model_validate(
            {
                "number": payload["number"],
                "title": payload["title"],
                "body": payload.get("body"),
                "author": author,
                "merged_at": payload["merged_at"],
                "labels": labels,
                "url": payload["html_url"],
            }
        )

    def _normalize_issue(self, payload: dict[str, Any]) -> RecentIssue:
        return RecentIssue.model_validate(
            {
                "number": payload["number"],
                "title": payload["title"],
                "state": GitHubIssueState(payload["state"]),
                "closed_at": payload.get("closed_at"),
                "url": payload["html_url"],
            }
        )

    def _extract_linked_issue_numbers(self, body: str | None) -> list[int]:
        if not body:
            return []
        return [int(match.group("number")) for match in _LINKED_ISSUE_PATTERN.finditer(body)]
