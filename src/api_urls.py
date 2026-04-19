from typing import Final


class JiraApi:
    BASE: Final[str] = "/rest/api/3"         # REST API 버전 base path
    ISSUE_SEARCH: Final[str] = "/search/jql" # 이슈 검색 endpoint


class NotionApi:
    NOTION_VERSION: Final[str] = "2026-03-11"          # Notion API 버전

    BASE_URL: Final[str] = "https://api.notion.com/v1" # REST API 버전 base path

    @classmethod
    def query_data_source_url(cls, data_source_id: str) -> str:
        return f"{NotionApi.BASE_URL}/data_sources/{data_source_id}/query"

    @classmethod
    def create_page_url(cls) -> str:
        return f"{NotionApi.BASE_URL}/pages"

    @classmethod
    def update_page_url(cls, page_id: str) -> str:
        return f"{NotionApi.BASE_URL}/pages/{page_id}"
