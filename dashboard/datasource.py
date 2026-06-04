"""
dashboard/datasource.py — 화면용 공고 목록 생성 모듈 (도메인: backend)

announcements.json(정본)을 읽고 analysis/{stable_id}/result.html(또는
result.md) 존재를 serve-time에 파생해 화면용 항목 목록을 만든다.

generate.py의 read_analysis / extract_executive_summary / extract_field
로직을 흡수. derive_stable_id는 scraper.core.ids 재사용(중복 정의 금지).

분석완료 판정 기준 (우선순위 순):
  1. result.html 이 존재하면 analyzed=True (신형 HTML 리포트)
  2. result.md  가 존재하면 analyzed=True (구형 마크다운 리포트, 하위호환)
저장소의 analyzed 플래그에는 의존하지 않는다.
"""

import json
import logging
import os
import re
import sys
from pathlib import Path

import yaml  # pip install pyyaml

logger = logging.getLogger(__name__)

# ── 경로 상수 ────────────────────────────────────────────────────────────────
# 이 파일은 dashboard/ 아래에 위치한다. 프로젝트 루트는 한 단계 위.
_DASHBOARD_DIR = Path(__file__).parent.resolve()
_PROJECT_ROOT = _DASHBOARD_DIR.parent

# scraper 패키지를 임포트하기 위해 sys.path에 추가
_SCRAPER_DIR = str(_PROJECT_ROOT / "scraper")
if _SCRAPER_DIR not in sys.path:
    sys.path.insert(0, _SCRAPER_DIR)

from core.ids import derive_stable_id  # noqa: E402 — sys.path 설정 후 임포트

# announcements.json 위치: scraper/output/announcements.json
_STORE_PATH = _PROJECT_ROOT / "scraper" / "output" / "announcements.json"

# 분석 결과 위치: analysis/{stable_id}/result.md (프로젝트 루트 기준)
_ANALYSIS_DIR = _PROJECT_ROOT / "analysis"

# scraper config 위치: scraper/config.yaml
_CONFIG_PATH = _PROJECT_ROOT / "scraper" / "config.yaml"


# ── 분석 결과 파싱 ───────────────────────────────────────────────────────────

def extract_executive_summary(md_text: str) -> str:
    """## Executive Summary 또는 ## 📌 Executive Summary 섹션 텍스트를 추출한다."""
    pattern = r"##\s*(?:📌\s*)?Executive Summary\s*\n(.*?)(?=\n##\s|\Z)"
    match = re.search(pattern, md_text, re.DOTALL)
    if not match:
        return ""
    return match.group(1).strip()


def extract_field(md_text: str) -> str:
    """Section 1 표에서 '사업 분야' 항목 값을 추출한다."""
    pattern = r"\|\s*\*{0,2}\s*사업\s*분야\s*\*{0,2}\s*\|([^|]+)\|"
    match = re.search(pattern, md_text)
    if not match:
        return ""
    raw = match.group(1).strip()
    # 셀 내에 파이프가 추가로 있으면 파싱 오류로 간주하고 빈 값 반환
    if r"\|" in raw or raw.count("|") >= 2:
        return ""
    return raw


def read_analysis(stable_id: str) -> dict:
    """
    analysis/{stable_id}/ 아래의 리포트 파일을 읽어 analyzed, summary, field를 반환한다.

    탐색 우선순위:
      1. result.html — 신형 완성형 HTML 리포트 (ArtifactRendering 출력)
         summary/field 추출을 위해 마크다운 파싱 대신 텍스트 검색을 사용한다.
      2. result.md   — 구형 마크다운 리포트 (하위호환, 기존 파일 보호)

    Returns:
        {
            "analyzed": bool,
            "report_format": "html" | "md" | "",  # 발견된 파일 형식
            "summary": str,
            "field": str,
        }
    """
    html_path = _ANALYSIS_DIR / stable_id / "result.html"
    md_path   = _ANALYSIS_DIR / stable_id / "result.md"

    # ── 신형 HTML 리포트 ─────────────────────────────────────────────────
    if html_path.exists():
        try:
            html_text = html_path.read_text(encoding="utf-8")
            # HTML에서 Executive Summary / 사업 분야 텍스트 추출
            # HTML 태그를 제거하고 마크다운 파서를 재사용한다.
            import re as _re
            plain = _re.sub(r"<[^>]+>", " ", html_text)
            return {
                "analyzed":      True,
                "report_format": "html",
                "summary":       extract_executive_summary(plain),
                "field":         extract_field(plain),
            }
        except Exception as e:
            logger.warning("result.html 읽기 실패 (%s): %s", stable_id, e)
            return {"analyzed": False, "report_format": "", "summary": "", "field": ""}

    # ── 구형 마크다운 리포트 (하위호환) ──────────────────────────────────
    if md_path.exists():
        try:
            md_text = md_path.read_text(encoding="utf-8")
            return {
                "analyzed":      True,
                "report_format": "md",
                "summary":       extract_executive_summary(md_text),
                "field":         extract_field(md_text),
            }
        except Exception as e:
            logger.warning("result.md 읽기 실패 (%s): %s", stable_id, e)
            return {"analyzed": False, "report_format": "", "summary": "", "field": ""}

    return {"analyzed": False, "report_format": "", "summary": "", "field": ""}


# ── 공개 함수 ────────────────────────────────────────────────────────────────

def load_search_keywords() -> list[str]:
    """
    scraper/config.yaml의 sites.g2b.search_keywords 목록을 반환한다.

    config가 없거나 키워드가 비어있으면 빈 리스트를 반환한다(에러 없이).
    """
    if not _CONFIG_PATH.exists():
        logger.warning("config.yaml 없음: %s", _CONFIG_PATH)
        return []

    try:
        with _CONFIG_PATH.open(encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        keywords = cfg.get("sites", {}).get("g2b", {}).get("search_keywords", [])
        return [str(k) for k in keywords] if keywords else []
    except Exception as e:
        logger.warning("config.yaml 읽기 실패: %s", e)
        return []


def load_announcements() -> tuple[list[dict], str]:
    """
    announcements.json을 읽고 분석 결과를 serve-time에 병합해
    화면용 공고 목록과 저장소 generated_at을 반환한다.

    is_new_batch 판정: record["최초수집일시"] == store["generated_at"]
    — 동일 스크랩 실행에서 삽입된 신규 레코드는 모두 같은 최초수집일시를 가지며,
      그 값이 해당 실행의 generated_at과 동일하다.

    Returns:
        (items, generated_at)
        items: 화면용 항목 dict 목록. 각 항목 키:
            stable_id, 공고명, 발주기관, 예산금액, 마감일시, 단계,
            판단상태, 다운로드상태, 첨부URL개수,
            analyzed(파생), field, summary,
            공고링크, 출처사이트,
            is_new_batch(파생 — 이번 수집 회차 신규 여부)
        generated_at: 최종 스크랩 실행 일시 문자열 (없으면 "")
    """
    if not _STORE_PATH.exists():
        logger.warning("announcements.json 없음: %s", _STORE_PATH)
        return [], ""

    try:
        store = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("announcements.json 로드 실패: %s", e)
        return [], ""

    generated_at = store.get("generated_at", "")
    records = store.get("announcements", {})
    items = []

    for sid, rec in records.items():
        analysis = read_analysis(sid)
        # 판정: 최초수집일시가 이번 수집 실행의 generated_at과 일치하면 신규
        is_new_batch = bool(
            generated_at and rec.get("최초수집일시", "") == generated_at
        )

        items.append({
            "stable_id":    sid,
            "공고명":        rec.get("공고명", ""),
            "발주기관":      rec.get("발주기관", ""),
            "예산금액":      rec.get("예산금액", ""),
            "마감일시":      rec.get("마감일시", ""),
            "단계":          rec.get("단계", ""),
            "판단상태":      rec.get("판단상태", "미검토"),
            "다운로드상태":  rec.get("다운로드상태", "none"),
            "첨부URL개수":   len(rec.get("첨부URL목록", [])),
            "analyzed":      analysis["analyzed"],
            "field":         analysis["field"],
            "summary":       analysis["summary"],
            "공고링크":      rec.get("공고링크", ""),
            "출처사이트":    rec.get("출처사이트", ""),
            "첨부파일경로":  rec.get("첨부파일경로", ""),
            "변환경로목록":  rec.get("변환경로목록", []),
            "삭제됨":        rec.get("삭제됨", False),
            "is_new_batch":  is_new_batch,
        })

    return items, generated_at


def get_record(stable_id: str) -> dict | None:
    """
    특정 stable_id의 원본 레코드를 반환한다. 없으면 None.

    app.py의 다운로드 처리가 원본 레코드(첨부URL목록 등)에 접근할 때 사용한다.
    """
    if not _STORE_PATH.exists():
        return None

    try:
        store = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return None

    return store.get("announcements", {}).get(stable_id)


def store_path() -> Path:
    """announcements.json 절대 경로를 반환한다. app.py의 upsert 호출에 사용."""
    return _STORE_PATH
