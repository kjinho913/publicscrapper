"""
단위 테스트: json_store.upsert() 신규/갱신 카운트 로직 검증

목적:
  - 빈 저장소에서 N건 upsert 시 전부 신규로 계산되는지 확인
  - 같은 배치 안에서 동일 stable_id가 중복되면 신규→갱신 오분류 발생 여부 확인
  - 기존 저장소에 있는 ID는 갱신으로, 없는 ID는 신규로 분류되는지 확인
  - 보존 필드(analyzed, 판단상태, 최초수집일시 등)가 갱신 시 유지되는지 확인
"""

import json
import sys
import tempfile
from pathlib import Path

import pytest

# scraper 패키지 경로 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.json_store import upsert, load_store, existing_ids


def _make_config(tmp_path: Path) -> dict:
    """테스트용 config — output 디렉터리를 임시 디렉터리로 설정한다."""
    return {"output": {"directory": str(tmp_path)}}


def _make_record(stable_id: str, title: str = "테스트공고") -> dict:
    """최소한의 수집 레코드 샘플을 반환한다."""
    return {
        "stable_id": stable_id,
        "공고번호": stable_id.split("-", 1)[-1],
        "공고명": title,
        "발주기관": "테스트기관",
        "출처사이트": "나라장터",
        "단계": "입찰공고",
        "공고일": "2026-06-01",
        "마감일시": "2026-06-30 18:00",
        "예산금액": "100,000,000",
        "내용요약": title,
        "공고링크": f"https://www.g2b.go.kr/test?bidPbancNo={stable_id.split('-', 1)[-1]}",
        "첨부파일수": 0,
        "첨부파일경로": "",
    }


# ─── TC-01: 빈 저장소 첫 upsert — 전부 신규 ──────────────────────────────────

class TestEmptyStoreFirstUpsert:
    """핵심 의심 지점: 빈 저장소에서 80건 upsert 시 전부 신규여야 한다."""

    def test_all_new_on_empty_store(self, tmp_path):
        config = _make_config(tmp_path)
        records = [_make_record(f"나라장터-ID{i:04d}") for i in range(80)]

        result = upsert(records, config)

        assert result["신규"] == 80, (
            f"빈 저장소에서 80건 삽입 시 신규 80건이어야 하지만 {result['신규']}건만 신규"
        )
        assert result["갱신"] == 0, (
            f"빈 저장소 첫 upsert에서 갱신은 0건이어야 하지만 {result['갱신']}건으로 집계"
        )

    def test_store_contains_all_records_after_empty_upsert(self, tmp_path):
        config = _make_config(tmp_path)
        records = [_make_record(f"나라장터-ID{i:04d}") for i in range(10)]

        upsert(records, config)
        store = load_store(config)

        assert len(store["announcements"]) == 10


# ─── TC-02: 배치 내 중복 stable_id — 신규→갱신 오분류 검사 ───────────────────

class TestDuplicateInSameBatch:
    """
    같은 배치(upsert 호출 1회)에 동일 stable_id가 2번 들어오면
    첫 번째가 신규로 삽입된 뒤 두 번째가 갱신으로 처리된다.
    이 동작 자체는 코드 논리상 자연스럽지만,
    실제 보고된 "신규 1건, 갱신 79건" 현상이 이 경로에서 비롯됐는지 확인한다.
    """

    def test_duplicate_in_batch_counts_as_one_new_one_update(self, tmp_path):
        config = _make_config(tmp_path)
        # 같은 stable_id를 2번 포함한 배치
        records = [
            _make_record("나라장터-DUPID", "첫번째공고"),
            _make_record("나라장터-DUPID", "두번째공고"),
        ]

        result = upsert(records, config)

        # 중복이 있으면 신규 1, 갱신 1 — 이것이 코드의 실제 동작
        assert result["신규"] == 1
        assert result["갱신"] == 1

    def test_unique_ids_no_false_update(self, tmp_path):
        """고유 stable_id 80건은 배치 내 중복 없이 전부 신규여야 한다."""
        config = _make_config(tmp_path)
        records = [_make_record(f"나라장터-UNIQUE{i:04d}") for i in range(80)]
        # stable_id 모두 다름을 확인
        ids = [r["stable_id"] for r in records]
        assert len(ids) == len(set(ids)), "테스트 전제: 모든 stable_id가 고유해야 함"

        result = upsert(records, config)

        assert result["신규"] == 80
        assert result["갱신"] == 0


# ─── TC-03: 2회 연속 실행 — 재수집 시 전부 갱신 ──────────────────────────────

class TestSecondRunAllUpdates:
    """두 번째 실행에서 동일 레코드 집합은 전부 갱신으로 집계되어야 한다."""

    def test_rerun_produces_zero_new(self, tmp_path):
        config = _make_config(tmp_path)
        records = [_make_record(f"나라장터-RR{i:04d}") for i in range(20)]

        upsert(records, config)           # 1회차
        result2 = upsert(records, config) # 2회차

        assert result2["신규"] == 0, (
            f"2회차 실행에서 신규는 0이어야 하지만 {result2['신규']}건"
        )
        assert result2["갱신"] == 20, (
            f"2회차 실행에서 갱신은 20건이어야 하지만 {result2['갱신']}건"
        )


# ─── TC-04: 보존 필드 유지 검사 ──────────────────────────────────────────────

class TestImmutableFieldsPreserved:
    """갱신 시 보존 필드(analyzed, 판단상태, 최초수집일시, 분석경로)는 바뀌지 않아야 한다."""

    def test_preserved_fields_on_update(self, tmp_path):
        config = _make_config(tmp_path)
        sid = "나라장터-PRESERVE001"
        records = [_make_record(sid)]

        # 1회차 삽입
        upsert(records, config)

        # 저장소에서 직접 보존 필드 변경 (사람이 분석을 완료한 상황 시뮬레이션)
        store_path = tmp_path / "announcements.json"
        with open(store_path, encoding="utf-8") as f:
            store = json.load(f)
        store["announcements"][sid]["analyzed"] = True
        store["announcements"][sid]["판단상태"] = "검토완료"
        store["announcements"][sid]["분석경로"] = "/some/analysis/path"
        original_first_collected = store["announcements"][sid]["최초수집일시"]
        with open(store_path, "w", encoding="utf-8") as f:
            json.dump(store, f, ensure_ascii=False, indent=2)

        # 2회차 재수집 (공고명이 바뀐 경우)
        updated_records = [_make_record(sid, "공고명이 변경됨")]
        upsert(updated_records, config)

        # 결과 확인
        store2 = load_store(config)
        rec = store2["announcements"][sid]

        assert rec["analyzed"] is True, "analyzed 필드가 덮어써짐"
        assert rec["판단상태"] == "검토완료", f"판단상태가 변경됨: {rec['판단상태']}"
        assert rec["분석경로"] == "/some/analysis/path", "분석경로가 변경됨"
        assert rec["최초수집일시"] == original_first_collected, "최초수집일시가 변경됨"

    def test_mutable_fields_updated(self, tmp_path):
        """갱신 시 변동 필드(공고명, 마감일시 등)는 새 값으로 바뀌어야 한다."""
        config = _make_config(tmp_path)
        sid = "나라장터-MUTABLE001"
        records = [_make_record(sid, "원래공고명")]
        upsert(records, config)

        updated = [_make_record(sid, "변경된공고명")]
        upsert(updated, config)

        store = load_store(config)
        rec = store["announcements"][sid]
        assert rec["공고명"] == "변경된공고명", "공고명이 갱신되지 않음"


# ─── TC-05: stable_id 없는 레코드 — fallback 처리 ───────────────────────────

class TestFallbackOnMissingStableId:
    """stable_id가 빈 문자열인 레코드는 공고번호+출처사이트 fallback 키를 써야 한다."""

    def test_fallback_key_used_when_stable_id_empty(self, tmp_path):
        config = _make_config(tmp_path)
        rec = _make_record("나라장터-FALLBACK001")
        rec["stable_id"] = ""  # stable_id 비움
        rec["공고번호"] = "FALLNUM001"
        rec["출처사이트"] = "나라장터"

        result = upsert([rec], config)
        store = load_store(config)

        assert result["신규"] == 1
        expected_key = "__fallback__나라장터__FALLNUM001"
        assert expected_key in store["announcements"], (
            f"fallback 키 '{expected_key}' 가 저장소에 없음"
        )

    def test_skip_record_with_no_stable_id_and_no_number(self, tmp_path):
        """stable_id도 공고번호도 없는 레코드는 건너뛰어야 한다."""
        config = _make_config(tmp_path)
        rec = _make_record("나라장터-SKIP001")
        rec["stable_id"] = ""
        rec["공고번호"] = ""

        result = upsert([rec], config)

        assert result["신규"] == 0
        assert result["갱신"] == 0


# ─── TC-06: existing_ids — 빈 저장소에서 빈 집합 반환 ───────────────────────

class TestExistingIds:
    def test_empty_store_returns_empty_set(self, tmp_path):
        config = _make_config(tmp_path)
        ids = existing_ids(config)
        assert ids == set()

    def test_existing_ids_after_upsert(self, tmp_path):
        config = _make_config(tmp_path)
        records = [_make_record(f"나라장터-EX{i:03d}") for i in range(5)]
        upsert(records, config)

        ids = existing_ids(config)
        assert len(ids) == 5
        assert "나라장터-EX000" in ids
        assert "나라장터-EX004" in ids


# ─── TC-07: 혼합 배치 — 신규+기존 혼재 ──────────────────────────────────────

class TestMixedBatch:
    """기존 3건 + 신규 2건이 섞인 배치: 신규 2, 갱신 3이어야 한다."""

    def test_mixed_new_and_existing(self, tmp_path):
        config = _make_config(tmp_path)
        existing_records = [_make_record(f"나라장터-OLD{i:03d}") for i in range(3)]
        upsert(existing_records, config)

        new_records = [_make_record(f"나라장터-NEW{i:03d}") for i in range(2)]
        mixed = existing_records + new_records
        result = upsert(mixed, config)

        assert result["신규"] == 2, f"신규 2건이어야 하지만 {result['신규']}건"
        assert result["갱신"] == 3, f"갱신 3건이어야 하지만 {result['갱신']}건"
