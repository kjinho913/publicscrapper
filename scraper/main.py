"""공공기관 사업공고 자동 수집기 — 단일 진입점

사용법:
  # 사이트별 직접 실행 (1개면 순차, 복수이면 병렬)
  python main.py --nipa
  python main.py --nipa --g2b --etri
  python main.py --all

  # config.yaml sources 기반 실행
  python main.py --once
  python main.py --schedule

  # 디버그
  python main.py --debug-nipa
  python main.py --debug-detail nipa <url>
"""

import argparse
import logging
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

from core.runner import run_site, load_config, save_tmp_json, load_tmp_json
from core.scheduler import run_once, _run_schedule, run_debug, run_debug_detail, setup_logging
from core.json_store import upsert as json_upsert

_ALL_SITES = ["nipa", "mss", "g2b", "nia", "etri"]
_DEFAULT_CONFIG = Path(__file__).parent / "config.yaml"
_LOG_DIR = Path(__file__).parent.parent / "logs"
_TMP_DIR = Path(__file__).parent / "output" / "tmp"


# ─── 워커 (ProcessPoolExecutor 별도 프로세스) ────────────────────────────────

def _worker(site_key: str, config: dict, log_dir_str: str, tmp_dir_str: str) -> dict:
    from pathlib import Path
    from core.runner import run_site, setup_logging, save_tmp_json

    setup_logging(Path(log_dir_str), site_key=site_key)
    filtered, stat = run_site(site_key, config)
    save_tmp_json(site_key, filtered, Path(tmp_dir_str))
    return stat


# ─── 단독 실행 ────────────────────────────────────────────────────────────────

def _run_single(site_key: str, config: dict) -> None:
    from core.runner import setup_logging as setup_logging_site
    setup_logging_site(_LOG_DIR, site_key=site_key)
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("[%s] 단독 실행 시작", site_key.upper())

    filtered, stat = run_site(site_key, config)
    result = json_upsert(filtered, config) if filtered else {"신규": 0, "갱신": 0}

    logger.info(
        "[%s] 완료 / 수집: %d건, 필터: %d건, 첨부: %d개, 신규: %d건, 갱신: %d건",
        site_key.upper(), stat["수집"], stat["필터"], stat["첨부"],
        result["신규"], result["갱신"],
    )
    logger.info("=" * 60)


# ─── 병렬 실행 ────────────────────────────────────────────────────────────────

def _run_parallel(sites: list[str], config: dict) -> None:
    from core.runner import setup_logging as setup_logging_site
    setup_logging_site(_LOG_DIR, site_key="all")
    logger = logging.getLogger("main")

    logger.info("=" * 60)
    logger.info("병렬 실행 시작: %s", ", ".join(sites))

    site_stats: list[dict] = []

    with ProcessPoolExecutor(max_workers=len(sites)) as executor:
        futures = {
            executor.submit(_worker, key, config, str(_LOG_DIR), str(_TMP_DIR)): key
            for key in sites
        }
        for future in as_completed(futures):
            key = futures[future]
            try:
                site_stats.append(future.result())
                logger.info("[%s] 워커 완료", key.upper())
            except Exception as exc:
                logger.error("[%s] 워커 실패: %s", key.upper(), exc)
                site_stats.append({"사이트": key, "수집": 0, "필터": 0, "첨부": 0, "오류": True})

    total_new = 0
    total_update = 0
    for key in sites:
        announcements = load_tmp_json(key, _TMP_DIR)
        if not announcements:
            continue
        result = json_upsert(announcements, config)
        total_new += result["신규"]
        total_update += result["갱신"]
        (_TMP_DIR / f"{key}.json").unlink(missing_ok=True)

    bar = "-" * 60
    logger.info(bar)
    logger.info("%-16s %6s  %6s  %6s", "사이트", "수집", "필터", "첨부")
    logger.info(bar)
    for s in site_stats:
        flag = "  [오류]" if s.get("오류") else ""
        logger.info("%-16s %5d건  %5d건  %5d개%s", s["사이트"], s["수집"], s["필터"], s["첨부"], flag)
    logger.info(bar)
    logger.info(
        "%-16s %5d건  %5d건  %5d개  (신규 %d건 / 갱신 %d건)",
        "합계",
        sum(s["수집"] for s in site_stats),
        sum(s["필터"] for s in site_stats),
        sum(s["첨부"] for s in site_stats),
        total_new,
        total_update,
    )
    logger.info(bar)
    logger.info("=" * 60)


# ─── 진입점 ───────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="공공기관 사업공고 자동 수집기",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""예시:
  python main.py --nipa
  python main.py --nipa --g2b
  python main.py --all
  python main.py --once
  python main.py --schedule
  python main.py --debug-nipa
  python main.py --debug-detail nipa <url>""",
    )

    site_group = parser.add_argument_group("사이트 선택 (복수 선택 시 병렬 실행)")
    site_group.add_argument("--all", action="store_true", help="전체 사이트 병렬 실행")
    for site in _ALL_SITES:
        site_group.add_argument(f"--{site}", action="store_true", help=f"{site.upper()} 실행")

    mode_group = parser.add_argument_group("실행 모드")
    mode_group.add_argument("--once", action="store_true", help="config.yaml sources 기반 순차 실행")
    mode_group.add_argument("--schedule", action="store_true", help="스케줄 모드 (config.yaml 시각에 반복 실행)")

    debug_group = parser.add_argument_group("디버그")
    debug_group.add_argument("--debug-nipa",  action="store_true", help="NIPA 목록 HTML 출력")
    debug_group.add_argument("--debug-mss",   action="store_true", help="MSS 목록 HTML 출력")
    debug_group.add_argument("--debug-nia",   action="store_true", help="NIA 목록 HTML 출력")
    debug_group.add_argument("--debug-etri",  action="store_true", help="ETRI 목록 HTML 출력")
    debug_group.add_argument("--debug-detail", nargs=2, metavar=("SITE", "URL"),
                             help="상세 페이지 HTML 출력 (예: --debug-detail nipa <url>)")

    parser.add_argument("--config", default=str(_DEFAULT_CONFIG), help="설정 파일 경로")
    args = parser.parse_args()

    config = load_config(Path(args.config))

    # 디버그 모드 (로깅 설정 불필요)
    if args.debug_detail:
        run_debug_detail(args.debug_detail[0], args.debug_detail[1], config)
        return

    for src in ("nipa", "mss", "nia", "etri"):
        if getattr(args, f"debug_{src}", False):
            run_debug(src, config)
            return

    # --once / --schedule 모드
    if args.schedule:
        setup_logging(_LOG_DIR)
        logger = logging.getLogger("main")
        _run_schedule(config, logger)
        return

    if args.once:
        setup_logging(_LOG_DIR)
        run_once(config)
        return

    # 사이트 선택 모드
    selected = _ALL_SITES if args.all else [s for s in _ALL_SITES if getattr(args, s)]
    if not selected:
        parser.print_help()
        sys.exit(1)

    if len(selected) == 1:
        _run_single(selected[0], config)
    else:
        _run_parallel(selected, config)


if __name__ == "__main__":
    main()
