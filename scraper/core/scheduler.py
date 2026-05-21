"""
스케줄/순차 실행 로직 및 디버그 헬퍼.
"""

import logging
import re
import sys
from datetime import datetime
from pathlib import Path

from core.downloader import download_attachments
from core.excel_writer import save_announcements
from core.filters import matches
from core.scrapers import NipaScraper, MssScraper, G2bScraper, NiaScraper, EtriScraper

_SCRAPER_MAP = {
    "nipa": NipaScraper,
    "mss":  MssScraper,
    "g2b":  G2bScraper,
    "nia":  NiaScraper,
    "etri": EtriScraper,
}

# 클래스 → config key 역방향 맵 (사이트별 필터 오버라이드에 사용)
_SCRAPER_KEY = {cls: key for key, cls in _SCRAPER_MAP.items()}


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


def enabled_scrapers(config: dict) -> list:
    sources = config.get("sources", {})
    return [
        cls(config)
        for key, cls in _SCRAPER_MAP.items()
        if sources.get(key, False)
    ]


def run_once(config: dict) -> None:
    logger = logging.getLogger("main")
    global_filter = config.get("filters", {})
    att_cfg = config.get("attachments", {})
    att_enabled = att_cfg.get("enabled", True)
    att_base_dir = Path(att_cfg.get("download_dir", "./output/attachments"))
    allowed_ext = att_cfg.get("allowed_extensions", None)
    max_mb = att_cfg.get("max_file_size_mb", 50)

    logger.info("=" * 60)
    logger.info("수집 시작: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

    site_stats: list[dict] = []
    total_added = 0

    for scraper in enabled_scrapers(config):
        source = scraper.SOURCE_NAME
        site_key = _SCRAPER_KEY.get(type(scraper), "")
        site_filter_override = config.get("sites", {}).get(site_key, {}).get("filters", {})
        filter_cfg = {**global_filter, **site_filter_override} if site_filter_override else global_filter

        stat = {"사이트": source, "수집": 0, "필터": 0, "첨부": 0, "오류": False}
        try:
            announcements = scraper.get_announcements()
        except Exception as exc:
            logger.error("[%s] 수집 중 예외: %s", source, exc)
            stat["오류"] = True
            site_stats.append(stat)
            continue

        stat["수집"] = len(announcements)
        filtered = [a for a in announcements if matches(a, filter_cfg)]
        stat["필터"] = len(filtered)
        logger.info("[%s] 수집 %d건 → 필터 후 %d건", source, len(announcements), len(filtered))

        # 첨부파일 다운로드
        if att_enabled:
            for ann in filtered:
                urls: list[str] = [
                    u for u in ann.pop("_attachment_urls", [])
                    if u and not u.startswith("javascript")
                ]
                if not urls:
                    continue
                dest = att_base_dir / source / _safe_dirname(ann.get("공고번호", "unknown"))
                count = download_attachments(
                    urls=urls,
                    dest_dir=dest,
                    session=scraper.session,
                    allowed_extensions=allowed_ext,
                    max_mb=max_mb,
                )
                ann["첨부파일수"] = count
                ann["첨부파일경로"] = str(dest.resolve()) if count > 0 else ""
                stat["첨부"] += count
        else:
            for ann in filtered:
                ann.pop("_attachment_urls", None)

        # 사이트별 시트에 저장
        if filtered:
            total_added += save_announcements(filtered, config, sheet_name=source)
        site_stats.append(stat)

    _log_summary(logger, site_stats, total_added)
    logger.info("=" * 60)


def _log_summary(logger, site_stats: list[dict], excel_added: int) -> None:
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
    logger.info("%-16s %5d건  %5d건  %5d개  (Excel 신규: %d건)",
                "합계", total_c, total_f, total_a, excel_added)
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


def _safe_dirname(name: str) -> str:
    """파일 시스템에 사용 불가한 문자를 제거한다."""
    return re.sub(r'[\\/*?:"<>|]', "_", name)[:80]
