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
        """Jira 이슈 검색 후 Issue 목록 반환 (nextPageToken 기반 페이지네이션).

        Returns:
            조회된 Issue 객체 리스트 (오류 시 빈 리스트)
        """
        url = f"{self.env.jira_url}{JiraApi.BASE}{JiraApi.ISSUE_SEARCH}"
        auth = HTTPBasicAuth(self.env.jira_email, self.env.jira_api_token)

        all_issues: List[Issue] = []
        next_page_token: str | None = None

        while True:
            # nextPageToken이 있으면 body에 포함해 다음 페이지 요청
            body = {
                "jql": self.config.query.jql,
                "maxResults": self.config.query.max_results,
                "fields": self.config.query.fields,
            }
            if next_page_token:
                body["nextPageToken"] = next_page_token

            response = requests.post(url=url, auth=auth, json=body)

            # 200: OK
            if response.status_code != 200:
                logger.error(f"Jira API 오류 {response.status_code}: {response.text}")
                return []

            data = response.json()
            issues = [
                Issue(key=raw["key"], fields=raw.get("fields", {}))
                for raw in data.get("issues", [])
            ]
            all_issues.extend(issues)

            # nextPageToken이 없으면 마지막 페이지
            next_page_token = data.get("nextPageToken")
            if not next_page_token:
                break

            logger.debug(f"다음 페이지 조회 중 (현재까지 {len(all_issues)}건)")

        logger.info(f"Jira 이슈 총 {len(all_issues)}건 조회 완료")
        return all_issues