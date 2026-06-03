"""
json_store.py — JSON 단일 원본 저장소.

저장 위치: scraper/output/announcements.json
구조:
    {
        "generated_at": "YYYY-MM-DD HH:MM:SS",
        "announcements": {
            "<stable_id>": { ...레코드... },
            ...
        }
    }

공개 함수:
    load_store(config)   → 전체 저장소 dict
    existing_ids(config) → stable_id 집합 (중복 판정용)
    upsert(records, config) → {"신규": N, "갱신": M}

병합 정책:
    신규(stable_id 없음): 그대로 추가, 최초수집일시=최종수집일시=현재
    기존(stable_id 있음): 변동 필드만 갱신, 보존 필드는 기존 값 유지

레코드 스키마:
    stable_id, 공고번호, 공고명, 발주기관, 출처사이트, 단계,
    공고일, 마감일시, 예산금액, 내용요약, 공고링크,
    첨부URL목록,          ← 수집 시점의 첨부파일 URL 목록 (버튼 다운로드 원본)
    첨부파일수, 첨부파일경로,   ← 비 g2b 사이트 자동 다운로드 결과 (g2b는 미사용)
    변환경로목록,         ← HWP→PDF 변환 후 로컬 경로 목록 (3단계에서 채움)
    다운로드상태,         ← "none" | "downloading" | "ready" | "failed"
    최초수집일시, 최종수집일시,
    analyzed, 분석경로, 판단상태,
    삭제됨               ← bool, 기본 false. 소프트 삭제 플래그 (재수집 시 유지)
"""

import json
import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

# scraper 패키지 루트 (= D:\...\webscrap\scraper)
# json_store.py 위치: scraper/core/json_store.py → .parent.parent = scraper/
_SCRAPER_ROOT = Path(__file__).resolve().parent.parent

# 갱신 시 덮어쓰는 필드 (수집 때마다 변할 수 있는 값)
_MUTABLE_FIELDS = {
    "공고명",
    "발주기관",
    "마감일시",
    "예산금액",
    "내용요약",
    "단계",
    "공고링크",
    "첨부URL목록",   # 최신 URL 반영 (다운로드 원본이므로 항상 최신으로 갱신)
}

# 갱신 시 절대 덮어쓰지 않는 필드 (사람이 채운 값 또는 다운로드 결과 보존)
_IMMUTABLE_FIELDS = {
    "최초수집일시",
    "analyzed",
    "분석경로",
    "판단상태",
    "첨부파일수",
    "첨부파일경로",
    "변환경로목록",  # 3단계에서 채운 변환 결과 보존
    "다운로드상태",  # 버튼 클릭 후 전이된 상태 보존
    "삭제됨",       # 사람이 누른 소프트 삭제 플래그 — 재수집 시에도 유지
}


def _store_path(config: dict) -> Path:
    out_cfg = config.get("output", {})
    out_dir = Path(out_cfg.get("directory", "./output"))
    # 상대경로면 scraper 패키지 루트 기준으로 resolve — cwd에 무관하게 항상 같은 위치
    if not out_dir.is_absolute():
        out_dir = _SCRAPER_ROOT / out_dir
    return out_dir / "announcements.json"


def _empty_store() -> dict:
    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "announcements": {},
    }


def _make_record(ann: dict, now_str: str) -> dict:
    """수집 데이터 dict → 저장소 레코드 dict (신규 삽입 용)."""
    return {
        "stable_id":    ann.get("stable_id", ""),
        "공고번호":      ann.get("공고번호", ""),
        "공고명":        ann.get("공고명", ""),
        "발주기관":      ann.get("발주기관", ""),
        "출처사이트":    ann.get("출처사이트", ""),
        "단계":          ann.get("단계", ""),
        "공고일":        ann.get("공고일", ""),
        "마감일시":      ann.get("마감일시", ""),
        "예산금액":      ann.get("예산금액", ""),
        "내용요약":      ann.get("내용요약", ""),
        "공고링크":      ann.get("공고링크", ""),
        "첨부URL목록":   ann.get("첨부URL목록", []),
        "첨부파일수":    ann.get("첨부파일수", 0),
        "첨부파일경로":  ann.get("첨부파일경로", ""),
        "변환경로목록":  [],          # 3단계에서 채움
        "다운로드상태":  "none",      # 버튼 클릭 전 기본값
        "최초수집일시":  now_str,
        "최종수집일시":  now_str,
        "analyzed":      False,
        "분석경로":      "",
        "판단상태":      "미검토",
        "삭제됨":        False,
    }


def load_store(config: dict) -> dict:
    """저장소 파일을 읽어 반환한다. 파일이 없으면 빈 구조를 반환한다."""
    path = _store_path(config)
    if not path.exists():
        return _empty_store()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if "announcements" not in data:
            logger.warning("[json_store] 저장소 형식이 올바르지 않음, 빈 상태로 초기화")
            return _empty_store()
        return data
    except Exception as exc:
        logger.error("[json_store] 저장소 로드 실패: %s — 빈 상태로 초기화", exc)
        return _empty_store()


def existing_ids(config: dict) -> set[str]:
    """저장소에 이미 있는 stable_id 집합을 반환한다. (중복 판정용)"""
    store = load_store(config)
    return set(store["announcements"].keys())


def upsert(records: list[dict], config: dict) -> dict:
    """
    레코드 목록을 저장소에 병합 저장한다.

    Args:
        records: 수집된 공고 dict 목록. 각 항목에 'stable_id' 키가 있어야 한다.
        config: 전체 config dict.

    Returns:
        {"신규": N, "갱신": M}
    """
    path = _store_path(config)
    path.parent.mkdir(parents=True, exist_ok=True)

    store = load_store(config)
    announcements = store["announcements"]

    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    new_count = 0
    update_count = 0

    for ann in records:
        sid = ann.get("stable_id", "")

        # stable_id가 비어 있으면 공고번호+출처사이트 fallback 키 사용
        if not sid:
            num = ann.get("공고번호", "")
            src = ann.get("출처사이트", "")
            if num:
                sid = f"__fallback__{src}__{num}"
                logger.warning(
                    "[json_store] stable_id 없음, fallback 키 사용: %s (공고명: %s)",
                    sid,
                    ann.get("공고명", ""),
                )
            else:
                logger.warning(
                    "[json_store] stable_id·공고번호 모두 없는 레코드 건너뜀: %s",
                    ann.get("공고명", ""),
                )
                continue

        if sid not in announcements:
            # 신규 삽입
            announcements[sid] = _make_record(ann, now_str)
            announcements[sid]["stable_id"] = sid
            new_count += 1
        else:
            # 기존 갱신 — 변동 필드만 덮어씀
            existing = announcements[sid]
            for field in _MUTABLE_FIELDS:
                if field in ann:
                    existing[field] = ann[field]
            existing["최종수집일시"] = now_str
            # 첨부파일 다운로드 결과는 새로 다운로드된 경우에만 갱신 (비g2b 사이트용)
            if ann.get("첨부파일수", 0):
                existing["첨부파일수"] = ann["첨부파일수"]
            if ann.get("첨부파일경로", ""):
                existing["첨부파일경로"] = ann["첨부파일경로"]
            # 기존 레코드에 새 필드가 없는 경우 기본값으로 마이그레이션
            existing.setdefault("첨부URL목록", [])
            existing.setdefault("변환경로목록", [])
            existing.setdefault("다운로드상태", "none")
            existing.setdefault("삭제됨", False)
            update_count += 1

    store["generated_at"] = now_str
    with open(path, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=2)

    logger.info(
        "[json_store] 저장 완료: %s (신규 %d건, 갱신 %d건)",
        path, new_count, update_count,
    )
    return {"신규": new_count, "갱신": update_count}
