"""
단일 사이트 실행 공통 로직.
"""

import json
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from core.downloader import download_attachments
from core.json_store import existing_ids as get_existing_ids
from core.filters import matches, refine_g2b
from core.scrapers import NipaScraper, MssScraper, G2bScraper, NiaScraper, EtriScraper

try:
    from core.playwright_helper import PlaywrightBrowser as _PlaywrightBrowser
    _PLAYWRIGHT_AVAILABLE = True
except ImportError:
    _PLAYWRIGHT_AVAILABLE = False

_SCRAPER_MAP = {
    "nipa": NipaScraper,
    "mss":  MssScraper,
    "g2b":  G2bScraper,
    "nia":  NiaScraper,
    "etri": EtriScraper,
}


def setup_logging(log_dir: Path, site_key: str) -> None:
    """사이트별 로그 파일을 사용하는 로깅을 설정한다.

    생성되는 파일: logs/scraper_{site_key}_YYYY-MM-DD.log
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    log_file = log_dir / f"scraper_{site_key}_{date_str}.log"
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


def load_config(config_path: Path) -> dict:
    load_dotenv()  # .env 파일이 있으면 환경변수로 로드
    with open(config_path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    # 환경변수 G2B_API_KEY가 있으면 config에 주입 (worker 프로세스에도 전달됨)
    g2b_key = os.environ.get("G2B_API_KEY")
    if g2b_key:
        cfg.setdefault("api_keys", {})["g2b_api_key"] = g2b_key
    return cfg


def run_site(site_key: str, config: dict) -> tuple[list[dict], dict]:
    """단일 사이트 전체 파이프라인 실행.

    스크래핑 → 필터링 → 첨부파일 다운로드를 수행한다.
    Excel 저장은 하지 않는다 — 호출자가 결정한다.

    Returns:
        (filtered_announcements, stat) 튜플.
    """
    logger = logging.getLogger(f"runner.{site_key}")

    cls = _SCRAPER_MAP.get(site_key)
    if cls is None:
        raise ValueError(f"알 수 없는 사이트 키: {site_key}")

    global_filter = config.get("filters", {})
    att_cfg = config.get("attachments", {})
    att_enabled = att_cfg.get("enabled", True)
    att_base_dir = Path(att_cfg.get("download_dir", "./output/attachments"))
    allowed_ext = att_cfg.get("allowed_extensions", None)
    max_mb = att_cfg.get("max_file_size_mb", 50)

    site_filter_override = config.get("sites", {}).get(site_key, {}).get("filters", {})
    filter_cfg = {**global_filter, **site_filter_override} if site_filter_override else global_filter

    # 나라장터 전용 필터 설정 (refine_g2b에서 사용)
    g2b_cfg = config.get("sites", {}).get("g2b", {}) if site_key == "g2b" else None

    scraper = cls(config)
    source = scraper.SOURCE_NAME
    stat = {"사이트": source, "수집": 0, "필터": 0, "첨부": 0, "오류": False}

    # Playwright 초기화 (JS 렌더링이 필요한 스크래퍼)
    pw = None
    if getattr(cls, "USE_PLAYWRIGHT_FOR_DETAIL", False) and _PLAYWRIGHT_AVAILABLE:
        pw = _PlaywrightBrowser()
        pw.__enter__()
        scraper.playwright_browser = pw
        logger.info("[%s] Playwright 브라우저 시작", source)

    try:
        try:
            announcements = scraper.get_announcements()
        except Exception as exc:
            logger.error("[%s] 수집 중 예외: %s", source, exc)
            stat["오류"] = True
            return [], stat

        # Playwright 쿠키를 requests session에 동기화 (다운로드 전)
        if pw is not None:
            pw.sync_cookies_to_session(scraper.session)

        stat["수집"] = len(announcements)
        # 나라장터는 refine_g2b() 전용 필터 사용; 나머지 사이트는 기존 matches() 유지
        if site_key == "g2b" and g2b_cfg is not None:
            filtered = [a for a in announcements if refine_g2b(a, g2b_cfg)]
        else:
            filtered = [a for a in announcements if matches(a, filter_cfg)]
        stat["필터"] = len(filtered)
        logger.info("[%s] 수집 %d건 → 필터 후 %d건", source, len(announcements), len(filtered))

        if site_key == "g2b":
            # [g2b 전용] 수집 시 자동 다운로드하지 않음 — URL만 레코드에 보관.
            # 다운로드는 대시보드 버튼 클릭 시 수행 (ADR-004 2단계).
            for ann in filtered:
                raw_urls = ann.pop("_attachment_urls", [])
                attachment_urls = list(dict.fromkeys(
                    u for u in raw_urls
                    if u and not u.startswith("javascript")
                ))
                ann["첨부URL목록"] = attachment_urls
                # stat["첨부"]는 0 유지 (다운로드 없음)
        elif att_enabled:
            # [비g2b 사이트] 기존 자동 다운로드 동작 유지
            existing_stable_ids = get_existing_ids(config)
            date_str = datetime.now().strftime("%Y-%m-%d")
            for ann in filtered:
                # stable_id 기준으로 이미 수집된 공고는 첨부파일 재다운로드 건너뜀
                sid = ann.get("stable_id", "")
                if sid and sid in existing_stable_ids:
                    ann.pop("_attachment_urls", None)
                    continue
                urls = list(dict.fromkeys(
                    u for u in ann.pop("_attachment_urls", [])
                    if u and not u.startswith("javascript")
                ))
                if not urls:
                    continue
                dest = att_base_dir / source / date_str
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

        return filtered, stat

    finally:
        if pw is not None:
            try:
                pw.__exit__(None, None, None)
                logger.info("[%s] Playwright 브라우저 종료", source)
            except Exception as exc:
                logger.debug("[%s] Playwright 종료 오류: %s", source, exc)


def save_tmp_json(site_key: str, announcements: list[dict], tmp_dir: Path) -> None:
    """결과를 임시 JSON 파일로 저장한다."""
    tmp_dir.mkdir(parents=True, exist_ok=True)
    with open(tmp_dir / f"{site_key}.json", "w", encoding="utf-8") as f:
        json.dump(announcements, f, ensure_ascii=False, indent=2)


def load_tmp_json(site_key: str, tmp_dir: Path) -> list[dict]:
    """임시 JSON 파일을 로드한다."""
    path = tmp_dir / f"{site_key}.json"
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _safe_dirname(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "_", name)[:80]
