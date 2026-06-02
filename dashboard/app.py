"""
dashboard/app.py — 나라장터 대시보드 Flask 로컬 웹앱 (도메인: backend)

엔드포인트:
    GET  /                          → index.html 서빙
    GET  /api/announcements         → 화면용 공고 목록(JSON)
    POST /api/download/<stable_id>  → 백그라운드 다운로드+변환 시작, 즉시 202 반환
    GET  /api/status/<stable_id>    → 해당 공고 다운로드 상태
    GET  /api/report/<stable_id>    → 분석 리포트(result.md → HTML 렌더링)
    GET  /api/pending-analysis      → 분석대기 공고 목록(PDF 경로 포함)

실행:
    python dashboard/app.py
    (또는 scripts/run_dashboard.bat 더블클릭)

전제:
    - 단일 사용자 로컬 환경 (인증·외부 배포 불필요)
    - 한글(HWP) 변환은 PC에 한컴 한글이 설치된 경우에만 동작
      미설치 시 다운로드는 완료되고 변환은 건너뜀(graceful)
"""

import json
import logging
import sys
import threading
from pathlib import Path

import markdown as _markdown  # pip install markdown (서버사이드 마크다운→HTML 변환)
from flask import Flask, jsonify, send_from_directory, abort

# ── 경로 설정 ────────────────────────────────────────────────────────────────
_APP_DIR = Path(__file__).parent.resolve()       # dashboard/
_PROJECT_ROOT = _APP_DIR.parent                  # 프로젝트 루트
_SCRAPER_DIR = str(_PROJECT_ROOT / "scraper")

if _SCRAPER_DIR not in sys.path:
    sys.path.insert(0, _SCRAPER_DIR)

# scraper 내부 모듈 임포트
import requests as _requests                      # noqa: E402
from core.downloader import download_attachments  # noqa: E402
from core.converter import convert_files          # noqa: E402
from core.json_store import load_store, upsert    # noqa: E402

import datasource                                  # noqa: E402

# ── Flask 앱 초기화 ───────────────────────────────────────────────────────────
app = Flask(__name__, static_folder=str(_APP_DIR), static_url_path="")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── 동시성 제어 ──────────────────────────────────────────────────────────────
# json_store 읽기-수정-쓰기에 Lock을 걸어 동시 다운로드 충돌을 방지한다.
_store_lock = threading.Lock()

# 다운로드 중인 stable_id 집합 (중복 클릭 방지)
_in_progress: set[str] = set()
_progress_lock = threading.Lock()

# config: json_store 함수가 필요로 하는 최소 config dict
# announcements.json 위치는 scraper/output/announcements.json
_CONFIG = {
    "output": {
        "directory": str(_PROJECT_ROOT / "scraper" / "output"),
    }
}

# 첨부파일 저장 루트: scraper/output/나라장터/{stable_id}/
_DOWNLOAD_ROOT = _PROJECT_ROOT / "scraper" / "output" / "나라장터"


# ── 헬퍼 ─────────────────────────────────────────────────────────────────────

def _update_record(stable_id: str, fields: dict) -> None:
    """
    announcements.json에서 stable_id 레코드의 특정 필드를 갱신한다.
    Lock을 잡고 읽기-수정-쓰기를 원자적으로 수행한다.
    """
    store_file = datasource.store_path()
    with _store_lock:
        try:
            store = json.loads(store_file.read_text(encoding="utf-8"))
        except Exception as e:
            logger.error("저장소 읽기 실패: %s", e)
            return

        rec = store.get("announcements", {}).get(stable_id)
        if rec is None:
            logger.warning("레코드 없음, 갱신 건너뜀: %s", stable_id)
            return

        for key, val in fields.items():
            rec[key] = val

        try:
            store_file.write_text(
                json.dumps(store, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception as e:
            logger.error("저장소 쓰기 실패: %s", e)


def _background_download(stable_id: str, urls: list[str]) -> None:
    """
    백그라운드 스레드에서 실행되는 다운로드+변환 작업.

    1. 첨부파일 다운로드 → scraper/output/나라장터/{stable_id}/
    2. HWP/HWPX → PDF 변환
    3. 레코드 갱신: 첨부파일경로, 변환경로목록, 다운로드상태, 판단상태
    """
    dest_dir = _DOWNLOAD_ROOT / stable_id
    logger.info("[DL] 시작: %s (%d개 URL)", stable_id, len(urls))

    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        session = _requests.Session()
        session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            )
        })

        # ── 1단계: 다운로드 ─────────────────────────────────────────────────
        downloaded_count = download_attachments(
            urls=urls,
            dest_dir=dest_dir,
            session=session,
        )
        logger.info("[DL] 다운로드 완료: %s (%d개)", stable_id, downloaded_count)

        # ── 2단계: HWP/HWPX → PDF 변환 ─────────────────────────────────────
        # HWP/HWPX만 변환 대상. 이미 PDF인 파일은 변환경로목록에 직접 포함.
        hwp_files = [
            str(p) for p in dest_dir.iterdir()
            if p.is_file() and p.suffix.lower() in {".hwp", ".hwpx"}
        ]
        pdf_files_direct = [
            str(p) for p in dest_dir.iterdir()
            if p.is_file() and p.suffix.lower() == ".pdf"
        ]

        conversion_results = convert_files(hwp_files) if hwp_files else {}
        converted_from_hwp = [
            v for v in conversion_results.values() if v is not None
        ]

        # 중복 제거: HWP에서 변환된 PDF와 직접 다운로드된 PDF를 합산
        converted_set = set(converted_from_hwp) | set(pdf_files_direct)
        converted_paths = sorted(converted_set)

        logger.info(
            "[DL] 변환 완료: %s (HWP→PDF %d개, 직접PDF %d개)",
            stable_id, len(converted_from_hwp), len(pdf_files_direct),
        )

        # ── 3단계: 레코드 갱신 ──────────────────────────────────────────────
        _update_record(stable_id, {
            "첨부파일경로":  str(dest_dir),
            "변환경로목록":  converted_paths,
            "다운로드상태":  "ready",
            "판단상태":      "분석대기",
        })
        logger.info("[DL] 완료 — 상태=ready: %s", stable_id)

    except Exception as e:
        logger.error("[DL] 오류 (%s): %s", stable_id, e, exc_info=True)
        _update_record(stable_id, {"다운로드상태": "failed"})

    finally:
        with _progress_lock:
            _in_progress.discard(stable_id)


# ── 엔드포인트 ───────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """탭1/탭2가 포함된 대시보드 HTML을 서빙한다."""
    return send_from_directory(str(_APP_DIR), "index.html")


@app.route("/api/announcements")
def api_announcements():
    """
    GET /api/announcements

    announcements.json + analysis/ result.md 파생 정보를 합쳐 목록을 반환한다.
    """
    items = datasource.load_announcements()
    return jsonify({"items": items, "total": len(items)})


@app.route("/api/download/<stable_id>", methods=["POST"])
def api_download(stable_id: str):
    """
    POST /api/download/<stable_id>

    백그라운드 다운로드+변환을 시작하고 즉시 202를 반환한다.
    - 첨부URL목록이 비었으면 즉시 "첨부없음" 처리 후 200
    - 이미 진행 중이면 409
    """
    rec = datasource.get_record(stable_id)
    if rec is None:
        abort(404, description=f"공고를 찾을 수 없습니다: {stable_id}")

    # 이미 다운로드 완료이면 즉시 ready 반환 (재다운로드 방지)
    current_status = rec.get("다운로드상태", "none")
    if current_status == "ready":
        logger.info("[DL] 이미 완료 상태, 즉시 반환: %s", stable_id)
        return jsonify({"status": "ready", "message": "이미 다운로드가 완료되어 있습니다."}), 200

    with _progress_lock:
        if stable_id in _in_progress:
            return jsonify({"status": "downloading", "message": "이미 다운로드 중입니다."}), 409

    urls: list[str] = rec.get("첨부URL목록", [])

    if not urls:
        # 첨부파일 URL이 없으면 즉시 처리 완료로 기록
        _update_record(stable_id, {
            "다운로드상태": "ready",
            "판단상태":     "분석대기",
            "변환경로목록": [],
        })
        logger.info("[DL] 첨부없음, 즉시 ready 처리: %s", stable_id)
        return jsonify({"status": "ready", "message": "첨부파일이 없습니다."}), 200

    # 다운로드 중 상태로 즉시 저장 후 백그라운드 시작
    with _progress_lock:
        _in_progress.add(stable_id)

    _update_record(stable_id, {"다운로드상태": "downloading"})

    t = threading.Thread(
        target=_background_download,
        args=(stable_id, urls),
        daemon=True,
        name=f"dl-{stable_id}",
    )
    t.start()

    return jsonify({"status": "downloading", "message": "백그라운드 다운로드를 시작했습니다."}), 202


@app.route("/api/status/<stable_id>")
def api_status(stable_id: str):
    """
    GET /api/status/<stable_id>

    해당 공고의 다운로드 상태와 변환 결과 건수를 반환한다.
    프론트엔드 폴링용.
    """
    rec = datasource.get_record(stable_id)
    if rec is None:
        abort(404, description=f"공고를 찾을 수 없습니다: {stable_id}")

    converted = rec.get("변환경로목록", [])
    analysis = datasource.read_analysis(stable_id)

    return jsonify({
        "stable_id":    stable_id,
        "다운로드상태": rec.get("다운로드상태", "none"),
        "판단상태":     rec.get("판단상태", "미검토"),
        "변환파일수":   len(converted),
        "analyzed":     analysis["analyzed"],
    })


@app.route("/api/report/<stable_id>")
def api_report(stable_id: str):
    """
    GET /api/report/<stable_id>

    analysis/{stable_id}/result.md를 읽어 마크다운→HTML로 변환하여 반환한다.
    result.md가 없으면 404.

    응답 JSON:
        stable_id  : 공고 식별자
        html       : 렌더링된 HTML 문자열 (탭2 인라인 표시용)
        summary    : Executive Summary 텍스트 (미리보기용)
        field      : 사업 분야
    """
    result_path = (
        _PROJECT_ROOT / "analysis" / stable_id / "result.md"
    )
    if not result_path.exists():
        abort(404, description="분석 결과가 아직 없습니다.")

    try:
        md_text = result_path.read_text(encoding="utf-8")
    except Exception as e:
        logger.error("result.md 읽기 실패 (%s): %s", stable_id, e)
        abort(500, description="리포트 읽기에 실패했습니다.")

    # 마크다운 → HTML 변환 (tables 확장: 표 지원 / nl2br 비활성화)
    html_body = _markdown.markdown(
        md_text,
        extensions=["tables", "fenced_code"],
    )

    analysis = datasource.read_analysis(stable_id)

    return jsonify({
        "stable_id": stable_id,
        "html":      html_body,
        "summary":   analysis["summary"],
        "field":     analysis["field"],
    })


@app.route("/api/pending-analysis")
def api_pending_analysis():
    """
    GET /api/pending-analysis

    판단상태=="분석대기" AND result.md가 없는(미분석) 공고 목록을 반환한다.
    사람이 Claude Code rfp-analyzer에 넘길 PDF 경로를 확인하기 위한 엔드포인트.

    응답 JSON:
        items: [
            {
                stable_id       : 공고 식별자
                공고명          : 공고 제목
                첨부파일경로    : 다운로드 폴더 경로 (문자열)
                변환경로목록    : PDF 경로 목록 (분석에 넣을 파일들)
            },
            ...
        ]
        total : 건수
    """
    all_items = datasource.load_announcements()

    pending = [
        {
            "stable_id":    item["stable_id"],
            "공고명":        item["공고명"],
            "첨부파일경로":  item.get("첨부파일경로", ""),
            "변환경로목록":  item.get("변환경로목록", []),
        }
        for item in all_items
        if item.get("판단상태") == "분석대기" and not item.get("analyzed", False)
    ]

    return jsonify({"items": pending, "total": len(pending)})


# ── 실행 진입점 ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 5050
    logger.info("대시보드 서버 시작: http://127.0.0.1:%d", port)
    # debug=False: 단일 사용자 로컬 환경. reloader 끄면 백그라운드 스레드 안전.
    app.run(host="127.0.0.1", port=port, debug=False, use_reloader=False)
