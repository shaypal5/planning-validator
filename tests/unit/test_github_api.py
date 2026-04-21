from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx

from planning_validator.github_api import GitHubEvidenceClient
from planning_validator.models import GitHubIssueState


def test_fetch_recent_merged_pull_requests_normalizes_and_filters_by_merged_at() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            page = parse_qs(request.url.query.decode()).get("page", ["1"])[0]
            if page == "1":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "number": 12,
                            "title": "Recent merged change",
                            "body": "Implements the first half.",
                            "merged_at": "2026-04-20T09:00:00Z",
                            "html_url": "https://github.com/acme/widgets/pull/12",
                            "labels": [{"name": "feature"}, {"name": "backend"}],
                            "user": {"login": "shay"},
                        },
                        {
                            "number": 11,
                            "title": "Closed but not merged",
                            "body": None,
                            "merged_at": None,
                            "html_url": "https://github.com/acme/widgets/pull/11",
                            "labels": [],
                            "user": {"login": "shay"},
                        },
                    ],
                )
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 10,
                        "title": "Older merged change",
                        "body": None,
                        "merged_at": "2026-04-18T09:00:00Z",
                        "html_url": "https://github.com/acme/widgets/pull/10",
                        "labels": [{"name": "feature"}],
                        "user": {"login": "older"},
                    }
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    pull_requests = client.fetch_recent_merged_pull_requests(
        merged_since=datetime(2026, 4, 19, tzinfo=UTC)
    )

    assert [pull_request.number for pull_request in pull_requests] == [12]
    assert pull_requests[0].title == "Recent merged change"
    assert pull_requests[0].author == "shay"
    assert pull_requests[0].labels == ["feature", "backend"]
    assert pull_requests[0].changed_files == []


def test_fetch_recent_merged_pull_requests_optionally_includes_changed_files() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 12,
                        "title": "Recent merged change",
                        "body": None,
                        "merged_at": "2026-04-20T09:00:00Z",
                        "html_url": "https://github.com/acme/widgets/pull/12",
                        "labels": [],
                        "user": {"login": "shay"},
                    }
                ],
            )
        if request.url.path == "/repos/acme/widgets/pulls/12/files":
            return httpx.Response(
                200,
                json=[
                    {"filename": "src/planning_validator/github_api.py"},
                    {"filename": "tests/unit/test_github_api.py"},
                ],
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    pull_requests = client.fetch_recent_merged_pull_requests(
        merged_since=datetime(2026, 4, 19, tzinfo=UTC),
        include_file_lists=True,
    )

    assert pull_requests[0].changed_files == [
        "src/planning_validator/github_api.py",
        "tests/unit/test_github_api.py",
    ]


def test_fetch_recent_merged_pull_requests_optionally_hydrates_linked_issues() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 12,
                        "title": "Recent merged change",
                        "body": "Fixes #44 and closes #44 after review. Resolves #45.",
                        "merged_at": "2026-04-20T09:00:00Z",
                        "html_url": "https://github.com/acme/widgets/pull/12",
                        "labels": [],
                        "user": {"login": "shay"},
                    }
                ],
            )
        if request.url.path == "/repos/acme/widgets/issues/44":
            return httpx.Response(
                200,
                json={
                    "number": 44,
                    "title": "Track milestone",
                    "state": "closed",
                    "closed_at": "2026-04-20T07:30:00Z",
                    "html_url": "https://github.com/acme/widgets/issues/44",
                },
            )
        if request.url.path == "/repos/acme/widgets/issues/45":
            return httpx.Response(
                200,
                json={
                    "number": 45,
                    "title": "Prepare release notes",
                    "state": "open",
                    "closed_at": None,
                    "html_url": "https://github.com/acme/widgets/issues/45",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    pull_requests = client.fetch_recent_merged_pull_requests(
        merged_since=datetime(2026, 4, 19, tzinfo=UTC),
        include_linked_issues=True,
    )

    assert [issue.number for issue in pull_requests[0].linked_issues] == [44, 45]
    assert pull_requests[0].linked_issues[0].state is GitHubIssueState.CLOSED
    assert pull_requests[0].linked_issues[1].state is GitHubIssueState.OPEN


def test_fetch_recent_merged_pull_requests_returns_empty_list_when_no_matches() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    assert (
        client.fetch_recent_merged_pull_requests(merged_since=datetime(2026, 4, 19, tzinfo=UTC))
        == []
    )


def test_fetch_recent_merged_pull_requests_reads_multiple_pages() -> None:
    first_page = [
        {
            "number": number,
            "title": f"Closed but not merged {number}",
            "body": None,
            "merged_at": None,
            "html_url": f"https://github.com/acme/widgets/pull/{number}",
            "labels": [],
            "user": {"login": "shay"},
        }
        for number in range(100, 200)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            page = parse_qs(request.url.query.decode()).get("page", ["1"])[0]
            if page == "1":
                return httpx.Response(200, json=first_page)
            if page == "2":
                return httpx.Response(
                    200,
                    json=[
                        {
                            "number": 12,
                            "title": "Second page merged change",
                            "body": None,
                            "merged_at": "2026-04-20T09:00:00Z",
                            "html_url": "https://github.com/acme/widgets/pull/12",
                            "labels": [],
                            "user": {"login": "shay"},
                        }
                    ],
                )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    pull_requests = client.fetch_recent_merged_pull_requests(
        merged_since=datetime(2026, 4, 19, tzinfo=UTC)
    )

    assert [pull_request.number for pull_request in pull_requests] == [12]
