"""
스케줄/순차 실행 로직 및 디버그 헬퍼.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from core.scrapers import NipaScraper, MssScraper, G2bScraper, NiaScraper, EtriScraper

_SCRAPER_MAP = {
    "nipa": NipaScraper,
    "mss":  MssScraper,
    "g2b":  G2bScraper,
    "nia":  NiaScraper,
    "etri": EtriScraper,
}


def setup_logging(log_dir: Path) -> None:
    """통합 로그 파일을 사용하는 로깅을 설정한다.

    생성되는 파일: logs/scraper_YYYY-MM-DD.log
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"scraper_{datetime.now().strftime('%Y-%m-%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(log_file, encoding="utf-8"),
        ],
        force=True,
    )


def enabled_site_keys(config: dict) -> list[str]:
    sources = config.get("sources", {})
    return [key for key in _SCRAPER_MAP if sources.get(key, False)]


def run_once(config: dict) -> None:
    """config.yaml sources에 활성화된 사이트를 순차 실행한다.

    스크래핑·필터링·첨부 처리는 runner.run_site()에 위임해
    모든 실행 경로(--once, --schedule, --g2b 등)가 동일 로직을 공유한다.
    """
    from core.runner import run_site
    from core.json_store import upsert as json_upsert

    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("수집 시작: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    site_stats: list[dict] = []
    total_new = 0
    total_update = 0

    for site_key in enabled_site_keys(config):
        filtered, stat = run_site(site_key, config)
        site_stats.append(stat)

        if filtered:
            result = json_upsert(filtered, config)
            total_new += result["신규"]
            total_update += result["갱신"]

    _log_summary(logger, site_stats, total_new, total_update)
    logger.info("=" * 60)


def _log_summary(logger, site_stats: list[dict], total_new: int, total_update: int) -> None:
    bar = "-" * 60
    header = f"{'사이트':<16} {'수집':>6}  {'필터':>6}  {'첨부':>6}"
    logger.info(bar)
    logger.info(header)
    logger.info(bar)
    for s in site_stats:
        flag = "  [오류]" if s["오류"] else ""
        logger.info("%-16s %5d건  %5d건  %5d개%s",
                    s["사이트"], s["수집"], s["필터"], s["첨부"], flag)
    logger.info(bar)
    total_c = sum(s["수집"] for s in site_stats)
    total_f = sum(s["필터"] for s in site_stats)
    total_a = sum(s["첨부"] for s in site_stats)
    logger.info("%-16s %5d건  %5d건  %5d개  (신규 %d건 / 갱신 %d건)",
                "합계", total_c, total_f, total_a, total_new, total_update)
    logger.info(bar)


def run_debug(source: str, config: dict) -> None:
    cls = _SCRAPER_MAP.get(source)
    if not cls:
        print(f"알 수 없는 소스: {source}. 선택 가능: {list(_SCRAPER_MAP.keys())}")
        return
    scraper = cls(config)
    if hasattr(scraper, "debug_html"):
        scraper.debug_html()
    else:
        print(f"{source} 스크래퍼에 debug_html 메서드가 없습니다.")


def run_debug_detail(source: str, url: str, config: dict) -> None:
    """상세 페이지 HTML을 출력한다 (첨부파일 셀렉터 확인용)."""
    cls = _SCRAPER_MAP.get(source)
    if not cls:
        print(f"알 수 없는 소스: {source}. 선택 가능: {list(_SCRAPER_MAP.keys())}")
        return
    scraper = cls(config)
    try:
        resp = scraper._get(url)
        print(f"\n=== {source.upper()} 상세 페이지 HTML ({url}) ===")
        print(resp.text[:8000])
    except Exception as exc:
        print(f"요청 실패: {exc}")


def _run_schedule(config: dict, logger) -> None:
    """config.yaml의 schedule.time에 맞춰 매일 실행."""
    try:
        import schedule
        import time
    except ImportError:
        logger.error("schedule 패키지가 설치되지 않았습니다: pip install schedule")
        return

    run_time = config.get("schedule", {}).get("time", "08:00")
    logger.info("스케줄 모드: 매일 %s에 실행 예약", run_time)

    schedule.every().day.at(run_time).do(run_once, config=config)

    # 시작 시 즉시 한 번 실행
    run_once(config)

    while True:
        schedule.run_pending()
        time.sleep(60)


