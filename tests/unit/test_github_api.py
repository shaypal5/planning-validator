from __future__ import annotations

from datetime import UTC, datetime
from urllib.parse import parse_qs

import httpx
import pytest
from pydantic import ValidationError

from planning_validator.github_api import GitHubApiError, GitHubEvidenceClient
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


def test_fetch_recent_merged_pull_requests_stops_after_first_older_merged_pr() -> None:
    page_requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            page = parse_qs(request.url.query.decode()).get("page", ["1"])[0]
            page_requests.append(page)
            if page == "1":
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
                        },
                        {
                            "number": 11,
                            "title": "Older merged change",
                            "body": None,
                            "merged_at": "2026-04-18T09:00:00Z",
                            "html_url": "https://github.com/acme/widgets/pull/11",
                            "labels": [],
                            "user": {"login": "shay"},
                        },
                    ],
                )
            raise AssertionError("Pagination should stop before requesting page 2")
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
    assert page_requests == ["1"]


def test_client_context_manager_closes_underlying_http_client() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(200, json=[])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    with GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    ) as client:
        assert not client._client.is_closed

    assert client._client.is_closed


def test_fetch_recent_merged_pull_requests_rejects_naive_merged_since() -> None:
    client = GitHubEvidenceClient(owner="acme", repo="widgets", token="token")

    with pytest.raises(ValueError, match="timezone info"):
        client.fetch_recent_merged_pull_requests(merged_since=datetime(2026, 4, 19))

    client.close()


def test_fetch_recent_merged_pull_requests_rejects_non_object_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(200, json=["unexpected"])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubApiError, match="pull request payload must be an object"):
        client.fetch_recent_merged_pull_requests(merged_since=datetime(2026, 4, 19, tzinfo=UTC))


def test_fetch_recent_merged_pull_requests_rejects_non_object_file_payloads() -> None:
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
            return httpx.Response(200, json=["unexpected"])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubApiError, match="file payload must be an object"):
        client.fetch_recent_merged_pull_requests(
            merged_since=datetime(2026, 4, 19, tzinfo=UTC),
            include_file_lists=True,
        )


def test_fetch_recent_merged_pull_requests_skips_blank_or_missing_file_names() -> None:
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
                    {"filename": ""},
                    {"filename": "docs/roadmap.md"},
                    {"ignored": "missing filename"},
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

    assert pull_requests[0].changed_files == ["docs/roadmap.md"]


def test_fetch_recent_merged_pull_requests_skips_linked_pull_request_issues() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 12,
                        "title": "Recent merged change",
                        "body": "Fixes #44 and fixes #45.",
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
                    "title": "Actual issue",
                    "state": "open",
                    "closed_at": None,
                    "html_url": "https://github.com/acme/widgets/issues/44",
                },
            )
        if request.url.path == "/repos/acme/widgets/issues/45":
            return httpx.Response(
                200,
                json={
                    "number": 45,
                    "title": "Actually a PR",
                    "state": "closed",
                    "closed_at": "2026-04-20T07:30:00Z",
                    "html_url": "https://github.com/acme/widgets/pull/45",
                    "pull_request": {"url": "https://api.github.com/repos/acme/widgets/pulls/45"},
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

    assert [issue.number for issue in pull_requests[0].linked_issues] == [44]


def test_fetch_recent_merged_pull_requests_rejects_non_object_issue_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 12,
                        "title": "Recent merged change",
                        "body": "Fixes #44.",
                        "merged_at": "2026-04-20T09:00:00Z",
                        "html_url": "https://github.com/acme/widgets/pull/12",
                        "labels": [],
                        "user": {"login": "shay"},
                    }
                ],
            )
        if request.url.path == "/repos/acme/widgets/issues/44":
            return httpx.Response(200, json=["unexpected"])
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubApiError, match="issue payload must be an object"):
        client.fetch_recent_merged_pull_requests(
            merged_since=datetime(2026, 4, 19, tzinfo=UTC),
            include_linked_issues=True,
        )


def test_get_json_wraps_http_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"message": "boom"})

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubApiError, match="GitHub API request failed"):
        client.fetch_recent_merged_pull_requests(merged_since=datetime(2026, 4, 19, tzinfo=UTC))


def test_get_json_wraps_invalid_json_payloads() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=b"<html>bad gateway</html>")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubApiError, match="returned invalid JSON"):
        client.fetch_recent_merged_pull_requests(merged_since=datetime(2026, 4, 19, tzinfo=UTC))


def test_fetch_recent_merged_pull_requests_rejects_non_list_top_level_payload() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(200, json={"unexpected": "object"})
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(GitHubApiError, match="returned non-list payload"):
        client.fetch_recent_merged_pull_requests(merged_since=datetime(2026, 4, 19, tzinfo=UTC))


def test_extract_linked_issue_numbers_returns_empty_for_missing_body() -> None:
    client = GitHubEvidenceClient(owner="acme", repo="widgets", token="token")

    assert client._extract_linked_issue_numbers(None) == []
    assert client._extract_linked_issue_numbers("") == []

    client.close()


def test_fetch_recent_merged_pull_requests_surfaces_invalid_issue_state_via_validation() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/acme/widgets/pulls":
            return httpx.Response(
                200,
                json=[
                    {
                        "number": 12,
                        "title": "Recent merged change",
                        "body": "Fixes #44.",
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
                    "state": "merged",
                    "closed_at": None,
                    "html_url": "https://github.com/acme/widgets/issues/44",
                },
            )
        raise AssertionError(f"Unexpected request: {request.method} {request.url}")

    client = GitHubEvidenceClient(
        owner="acme",
        repo="widgets",
        token="token",
        transport=httpx.MockTransport(handler),
    )

    with pytest.raises(ValidationError, match="state"):
        client.fetch_recent_merged_pull_requests(
            merged_since=datetime(2026, 4, 19, tzinfo=UTC),
            include_linked_issues=True,
        )
