from dataclasses import dataclass
from typing import List
import requests
from requests.auth import HTTPBasicAuth
from loguru import logger

from api_urls import JiraApi
from env import Env
from config import SyncConfig


@dataclass
class Issue:
    """Jira 이슈 데이터를 담는 클래스."""
    key: str    # 이슈 키 (예: PROJECT-123)
    fields: dict  # Jira API 응답의 fields 객체


class JiraClient:
    """Jira API 클라이언트, 동기화 항목 관리."""

    env: Env
    config: SyncConfig

    def __init__(self, env: Env, config: SyncConfig) -> None:
        self.env = env
        self.config = config

    def issue_search(self) -> List[Issue]:
        """Jira 이슈 검색 후 Issue 목록 반환.

        Returns:
            조회된 Issue 객체 리스트 (오류 시 빈 리스트)
        """
        response = requests.post(
            url=f"{self.env.jira_url}{JiraApi.BASE}{JiraApi.ISSUE_SEARCH}",
            auth=HTTPBasicAuth(self.env.jira_email, self.env.jira_api_token),
            json={
                "jql": self.config.query.jql,
                "maxResults": self.config.query.max_results,
                "fields": self.config.query.fields,
            }
        )

        # 200: OK
        if response.status_code != 200:
            logger.error(f"Jira API 오류 {response.status_code}: {response.text}")
            return []

        issues = [
            Issue(key=raw["key"], fields=raw.get("fields", {}))
            for raw in response.json().get("issues", [])
        ]
        
        return issues