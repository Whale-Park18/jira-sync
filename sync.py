import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

import click
from loguru import logger

from config import load_config, SyncConfig
from env import load_env, Env
from jira_client import JiraClient
from notion_client import NotionDatabase

@click.command()
@click.option(
    "--config",
    default="sync_config.yaml",
    type=click.Path(exists=True, dir_okay=False, readable=True), # 파일 검증 추가
    help="매핑 설정 파일 경로"
)
@click.option(
    "--dry-run",
    is_flag=True,
    help="실제 반영 없이 결과만 출력"
)
def main(config: str, dry_run: bool) -> None:
    """Jira → Notion 단방향 동기화

    Args:
        config: 동기화 설정 파일 경로
        dry_run: Notion에 쓰지 않고 매핑 결과만 출력
    """

    # 파일 저장 설정 (500MB마다 새 파일 생성, 10일치 보관)
    logger.add("sync.log", rotation="500 MB", retention="10 days", level="INFO")
    logger.info(f"config : {config}, dry-run : {dry_run}")

    # 설정 파일 읽기
    env: Env = load_env()
    sync_config: SyncConfig = load_config(config)

    logger.debug("query:")
    logger.debug(f"    jql: {sync_config.query.jql}")
    logger.debug(f"    max_results: {sync_config.query.max_results}")
    logger.debug(f"    fields: {sync_config.query.fields}")

    logger.debug("mappings:")
    for mapping in sync_config.mappings:
        logger.debug(f"    - jira_field: {mapping.jira_field}")
        logger.debug(f"      notion_property: {mapping.notion_property}")
        logger.debug(f"      notion_type: {mapping.notion_type}")

    # Jira 이슈 검색
    logger.info("Jira 이슈 검색 시작")
    
    jira_client = JiraClient(env, sync_config)
    issues = jira_client.issue_search()

    logger.info(f"Jira 조회된 이슈 수: {len(issues)}")
    logger.info("Jira 이슈 검색 완료")

    # Notion DB 갱신
    if not dry_run:
        logger.info("Notion DB 갱신 시작")

        notion_client = NotionDatabase(env)
        notion_client.upsert(issues, sync_config.mappings, sync_config.notion_query)

        logger.info("Notion DB 갱신 완료")

if __name__ == "__main__":
    main()
