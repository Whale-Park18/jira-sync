from unittest.mock import MagicMock, patch
import pytest

from env import Env
from config import SyncConfig, QueryConfig, FieldMapping
from jira_client import JiraClient, Issue


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def env():
    return Env(
        jira_url="https://test.atlassian.net",
        jira_email="test@example.com",
        jira_api_token="token",
        notion_api_key="notion-secret",
        notion_data_source_id="db-id",
    )

@pytest.fixture
def sync_config():
    return SyncConfig(
        query=QueryConfig(jql="project = TEST", max_results=10, fields=["summary"]),
        notion_query={},
        mappings=[FieldMapping(jira_field="key", notion_property="issue", notion_type="title")],
    )

@pytest.fixture
def client(env, sync_config):
    return JiraClient(env, sync_config)


# ──────────────────────────────────────────────
# issue_search
# ──────────────────────────────────────────────

class TestIssueSearch:

    @patch("jira_client.requests.post")
    def test_success_returns_issues(self, mock_post, client):
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "issues": [
                    {"key": "TEST-1", "fields": {"summary": "버그"}},
                    {"key": "TEST-2", "fields": {"summary": "기능"}},
                ]
            },
        )
        issues = client.issue_search()
        assert len(issues) == 2
        assert issues[0].key == "TEST-1"
        assert issues[0].fields["summary"] == "버그"
        assert issues[1].key == "TEST-2"

    @patch("jira_client.requests.post")
    def test_empty_issues(self, mock_post, client):
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"issues": []})
        assert client.issue_search() == []

    @patch("jira_client.requests.post")
    def test_api_error_returns_empty(self, mock_post, client):
        mock_post.return_value = MagicMock(status_code=401, text="Unauthorized")
        assert client.issue_search() == []

    @patch("jira_client.requests.post")
    def test_request_body(self, mock_post, client):
        """JQL, maxResults, fields가 올바르게 전송되는지 확인."""
        mock_post.return_value = MagicMock(status_code=200, json=lambda: {"issues": []})
        client.issue_search()
        _, kwargs = mock_post.call_args
        assert kwargs["json"]["jql"] == "project = TEST"
        assert kwargs["json"]["maxResults"] == 10
        assert kwargs["json"]["fields"] == ["summary"]

    @patch("jira_client.requests.post")
    def test_missing_fields_defaults_to_empty(self, mock_post, client):
        """fields 키 없는 이슈는 빈 dict로 처리."""
        mock_post.return_value = MagicMock(
            status_code=200,
            json=lambda: {"issues": [{"key": "TEST-3"}]},
        )
        issues = client.issue_search()
        assert issues[0].fields == {}

    @patch("jira_client.requests.post")
    def test_pagination_fetches_all_pages(self, mock_post, client):
        """nextPageToken이 있으면 다음 페이지까지 모두 조회."""
        # 1페이지: nextPageToken 포함, 2페이지: nextPageToken 없음
        responses = [
            MagicMock(
                status_code=200,
                json=lambda: {
                    "issues": [{"key": "TEST-1", "fields": {}}],
                    "nextPageToken": "token-abc",
                },
            ),
            MagicMock(
                status_code=200,
                json=lambda: {
                    "issues": [{"key": "TEST-2", "fields": {}}],
                },
            ),
        ]
        mock_post.side_effect = responses

        issues = client.issue_search()

        assert len(issues) == 2
        assert issues[0].key == "TEST-1"
        assert issues[1].key == "TEST-2"
        assert mock_post.call_count == 2

    @patch("jira_client.requests.post")
    def test_pagination_sends_next_page_token(self, mock_post, client):
        """두 번째 요청 body에 nextPageToken이 포함되는지 확인."""
        responses = [
            MagicMock(
                status_code=200,
                json=lambda: {"issues": [{"key": "TEST-1", "fields": {}}], "nextPageToken": "tok-1"},
            ),
            MagicMock(
                status_code=200,
                json=lambda: {"issues": [], "nextPageToken": None},
            ),
        ]
        mock_post.side_effect = responses

        client.issue_search()

        second_call_body = mock_post.call_args_list[1][1]["json"]
        assert second_call_body["nextPageToken"] == "tok-1"

    @patch("jira_client.requests.post")
    def test_pagination_error_on_second_page_returns_empty(self, mock_post, client):
        """두 번째 페이지에서 오류 시 빈 리스트 반환."""
        responses = [
            MagicMock(
                status_code=200,
                json=lambda: {"issues": [{"key": "TEST-1", "fields": {}}], "nextPageToken": "tok-1"},
            ),
            MagicMock(status_code=500, text="Internal Server Error"),
        ]
        mock_post.side_effect = responses

        issues = client.issue_search()
        assert issues == []
