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
@click.option(
    "--scan-mode",
    type=click.Choice(["keys", "filtered", "full"]),  # 향후 모드 확장(incremental 등) 용이
    default="keys",
    show_default=True,
    help="keys(기본): JQL 결과 키만 or-필터로 조회 (중복 방지 + 효율적) / "
         "filtered: notion_query.filter 적용 / full: filter 제거 후 전체 페이지 스캔 (속도 느림)"
)
def main(config: str, dry_run: bool, scan_mode: str) -> None:
    """Jira → Notion 단방향 동기화

    Args:
        config: 동기화 설정 파일 경로
        dry_run: Notion에 쓰지 않고 매핑 결과만 출력
        scan_mode: "keys"(기본)이면 JQL 결과 이슈 키만 or-필터로 조회 → notion_query.filter와
                   무관하게 기존 페이지를 찾아 중복 생성 방지(ceil(N/100) 요청).
                   "filtered"이면 notion_query.filter를 적용해 lookup.
                   "full"이면 filter 제거 후 전체 페이지 스캔 → 필터 밖 페이지(예: 완료 상태)도
                   중복 판별 대상에 포함.
    """

    # 파일 저장 설정 (500MB마다 새 파일 생성, 10일치 보관)
    logger.add("sync.log", rotation="500 MB", retention="10 days", level="INFO")
    # CLI 옵션 식별자와 로그 키를 일치시켜 추적 용이
    logger.info(f"config : {config}, dry-run : {dry_run}, scan-mode : {scan_mode}")

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

    # Notion DB 갱신 (dry-run이어도 lookup은 수행하고 쓰기만 생략 → update/created 예측 로그 출력)
    logger.info("Notion DB 갱신 시뮬레이션 시작 (dry-run)" if dry_run else "Notion DB 갱신 시작")

    notion_client = NotionDatabase(env)
    # scan_mode·dry_run을 upsert에 전달 (filter 적용 여부 / 실제 쓰기 여부 결정)
    notion_client.upsert(
        issues, sync_config.mappings, sync_config.notion_query, scan_mode=scan_mode, dry_run=dry_run
    )

    logger.info("Notion DB 갱신 시뮬레이션 완료 (dry-run)" if dry_run else "Notion DB 갱신 완료")

if __name__ == "__main__":
    main()
