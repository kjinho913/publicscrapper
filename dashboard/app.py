"""
dashboard/app.py — 나라장터 대시보드 Flask 로컬 웹앱 (도메인: backend)

엔드포인트:
    GET  /                                    → index.html 서빙
    GET  /api/announcements                   → 화면용 공고 목록(JSON)
    POST /api/download/<stable_id>            → 백그라운드 다운로드+변환 시작, 즉시 202 반환
    GET  /api/status/<stable_id>              → 해당 공고 다운로드 상태
    GET  /api/report/<stable_id>              → 분석 리포트 HTML 원본 반환
                                                result.html(신형) 우선, 없으면 구형 result.md → HTML 변환
    GET  /api/report/<stable_id>/download     → result.html을 파일 첨부(attachment)로 반환
                                                ※ /api/download (첨부파일 수집용)와는 별개 기능
    GET  /api/pending-analysis                → 분석대기 공고 목록(PDF 경로 포함)

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

import re as _re
from flask import Flask, jsonify, send_from_directory, send_file, abort, request

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

    추가 응답 필드:
        latest_collected_at : 최종 스크랩 실행 일시 (store.generated_at)
        new_count           : 이번 수집 회차 신규 건수 (is_new_batch == True인 항목 수)
    각 item에 is_new_batch(bool) 파생 필드 포함.
    """
    items, generated_at = datasource.load_announcements()
    keywords = datasource.load_search_keywords()
    new_count = sum(1 for it in items if it.get("is_new_batch"))
    return jsonify({
        "items":               items,
        "total":               len(items),
        "keywords":            keywords,
        "latest_collected_at": generated_at,
        "new_count":           new_count,
    })


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

    분석 리포트 HTML 원본을 반환한다.

    탐색 우선순위:
      1. analysis/{stable_id}/result.html  — 신형 완성형 HTML 리포트
         변환 없이 원본 HTML 문자열을 그대로 반환한다.
      2. analysis/{stable_id}/result.md    — 구형 마크다운 리포트 (하위호환)
         기존 band-aid 보정 + markdown 변환을 적용해 HTML 조각을 반환한다.
         ※ 구형 파일을 새로 생성하지는 않는다. 기존 데이터 보호 목적.

    result.html / result.md 모두 없으면 404.

    응답 JSON:
        stable_id     : 공고 식별자
        html          : 렌더링된 HTML 문자열 (탭2 iframe srcdoc 또는 innerHTML용)
        report_format : "html" | "md"  (프런트가 렌더 방식을 구분할 때 사용)
        summary       : Executive Summary 텍스트 (미리보기용)
        field         : 사업 분야
    """
    analysis_dir = _PROJECT_ROOT / "analysis" / stable_id
    html_path    = analysis_dir / "result.html"
    md_path      = analysis_dir / "result.md"

    # ── 신형: result.html 원본 서빙 ─────────────────────────────────────
    if html_path.exists():
        try:
            html_text = html_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("result.html 읽기 실패 (%s): %s", stable_id, e)
            abort(500, description="리포트 읽기에 실패했습니다.")

        analysis = datasource.read_analysis(stable_id)
        return jsonify({
            "stable_id":     stable_id,
            "html":          html_text,
            "report_format": "html",
            "summary":       analysis["summary"],
            "field":         analysis["field"],
        })

    # ── 구형: result.md → HTML 변환 (하위호환, 기존 데이터 보호) ────────
    if md_path.exists():
        try:
            md_text = md_path.read_text(encoding="utf-8")
        except Exception as e:
            logger.error("result.md 읽기 실패 (%s): %s", stable_id, e)
            abort(500, description="리포트 읽기에 실패했습니다.")

        # 구형 마크다운 band-aid 보정
        import markdown as _markdown  # noqa: F401 — 구형 파일 처리 시에만 사용
        _BOX_FIRST = set("┌┐└┘├┤┬┴┼│─")
        md_lines = md_text.split("\n")
        md_lines = [_re.sub(r"^ {1,8}", "", line) for line in md_lines]
        md_clean = "\n".join(md_lines)
        md_clean = _re.sub(r"---\s*\n\s*(Executive Summary)", r"## \1", md_clean)
        md_clean = _re.sub(r"---\s*\n\s*(\d+\.\s)", r"## \1", md_clean)
        md_clean = _re.sub(r"^▎\s*", "> ", md_clean, flags=_re.MULTILINE)
        md_clean = _re.sub(r"^(\d+-[A-Z0-9]\.\s)", r"### \1", md_clean, flags=_re.MULTILINE)

        out_lines = []
        in_box = False
        for line in md_clean.split("\n"):
            stripped = line.strip()
            is_box = bool(stripped) and stripped[0] in _BOX_FIRST
            if is_box:
                if not in_box:
                    out_lines.append("```")
                    in_box = True
                out_lines.append(line)
            else:
                if in_box:
                    out_lines.append("```")
                    in_box = False
                out_lines.append(line)
        if in_box:
            out_lines.append("```")
        md_clean = "\n".join(out_lines)

        html_body = _markdown.markdown(md_clean, extensions=["tables", "fenced_code"])
        analysis = datasource.read_analysis(stable_id)
        return jsonify({
            "stable_id":     stable_id,
            "html":          html_body,
            "report_format": "md",
            "summary":       analysis["summary"],
            "field":         analysis["field"],
        })

    # ── 리포트 없음 ──────────────────────────────────────────────────────
    abort(404, description="분석 결과가 아직 없습니다.")


@app.route("/api/report/<stable_id>/download")
def api_report_download(stable_id: str):
    """
    GET /api/report/<stable_id>/download

    analysis/{stable_id}/result.html을 파일 첨부(attachment)로 내려준다.
    사용자가 브라우저에서 "다운로드" 버튼을 클릭할 때 호출된다.

    result.html이 없으면 404.
    ※ POST /api/download/<stable_id> (첨부파일 수집 트리거)와는 전혀 다른 기능.
    """
    html_path = _PROJECT_ROOT / "analysis" / stable_id / "result.html"
    if not html_path.exists():
        abort(404, description="다운로드할 result.html이 없습니다. 신형 HTML 리포트만 다운로드 가능합니다.")

    return send_file(
        str(html_path),
        mimetype="text/html",
        as_attachment=True,
        download_name=f"{stable_id}_report.html",
    )


_VALID_STATUSES = {"미검토", "관심", "참여검토", "제외"}


@app.route("/api/announcement/<stable_id>/delete", methods=["POST"])
def api_delete(stable_id: str):
    """
    POST /api/announcement/<stable_id>/delete

    해당 공고를 소프트 삭제(삭제됨=true)한다.
    재수집 시에도 삭제 상태가 유지된다(부활 방지).
    """
    rec = datasource.get_record(stable_id)
    if rec is None:
        abort(404, description=f"공고를 찾을 수 없습니다: {stable_id}")

    _update_record(stable_id, {"삭제됨": True})
    logger.info("[DELETE] 소프트 삭제: %s", stable_id)
    return jsonify({"stable_id": stable_id, "삭제됨": True}), 200


@app.route("/api/announcement/<stable_id>/restore", methods=["POST"])
def api_restore(stable_id: str):
    """
    POST /api/announcement/<stable_id>/restore

    소프트 삭제된 공고를 복원(삭제됨=false)한다.
    """
    rec = datasource.get_record(stable_id)
    if rec is None:
        abort(404, description=f"공고를 찾을 수 없습니다: {stable_id}")

    _update_record(stable_id, {"삭제됨": False})
    logger.info("[RESTORE] 복원: %s", stable_id)
    return jsonify({"stable_id": stable_id, "삭제됨": False}), 200


@app.route("/api/announcement/<stable_id>/status", methods=["POST"])
def api_set_status(stable_id: str):
    """
    POST /api/announcement/<stable_id>/status
    Body: {"판단상태": "미검토" | "관심" | "참여검토" | "제외"}

    판단상태를 인라인으로 변경한다.
    """
    rec = datasource.get_record(stable_id)
    if rec is None:
        abort(404, description=f"공고를 찾을 수 없습니다: {stable_id}")

    body = request.get_json(silent=True) or {}
    new_status = body.get("판단상태", "")
    if new_status not in _VALID_STATUSES:
        abort(400, description=f"유효하지 않은 판단상태입니다: {new_status!r}. 허용값: {sorted(_VALID_STATUSES)}")

    _update_record(stable_id, {"판단상태": new_status})
    logger.info("[STATUS] 판단상태 변경: %s → %s", stable_id, new_status)
    return jsonify({"stable_id": stable_id, "판단상태": new_status}), 200


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
    all_items, _generated_at = datasource.load_announcements()

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
