"""
test_scheduler_run_once.py

단위 테스트(unit test): scheduler.run_once()가 runner.run_site()에 위임하는지,
자체 download_attachments 호출이 없는지, 통계/로그 출력 구조가 유지되는지 검증.

용어 설명:
  - 단위 테스트: 코드 한 조각(여기서는 run_once 함수)을 외부 의존성 없이 격리해서 검사하는 테스트.
  - 모킹(mocking): 실제 네트워크/파일 대신 가짜 객체를 주입해 함수 동작만 검사하는 기법.

패치 경로 주의사항:
  run_once()는 함수 본문 안에서 `from core.runner import run_site`를 지역 import한다.
  따라서 `core.scheduler.run_site`는 모듈 수준 속성으로 존재하지 않는다.
  올바른 패치 대상은 import 원본인 `core.runner.run_site`이다.
  (Python 모킹 원칙: 실제 객체가 사용되는 위치가 아니라, 정의된 위치에서 패치한다)
"""
import logging
import sys
import unittest
from unittest.mock import MagicMock, patch, call
from pathlib import Path

# scraper 루트를 sys.path에 추가
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scheduler import run_once, enabled_site_keys


# ──────────────────────────────────────────────────────────────
# 테스트 픽스처
# ──────────────────────────────────────────────────────────────

MINIMAL_CONFIG = {
    "sources": {"g2b": True, "nipa": False, "mss": False, "nia": False, "etri": False},
    "output": {"directory": "./output"},
    "attachments": {"enabled": True, "download_dir": "./output/attachments"},
}

MULTI_SITE_CONFIG = {
    "sources": {"g2b": True, "nipa": True, "mss": False, "nia": False, "etri": False},
    "output": {"directory": "./output"},
    "attachments": {"enabled": True, "download_dir": "./output/attachments"},
}


# ──────────────────────────────────────────────────────────────
# 1. run_once가 run_site를 호출하는지
# ──────────────────────────────────────────────────────────────

class TestRunOnceCallsRunSite(unittest.TestCase):
    """run_once()가 runner.run_site()에 위임하는지 검증."""

    def _make_stat(self, site="나라장터"):
        return {"사이트": site, "수집": 10, "필터": 5, "첨부": 0, "오류": False}

    @patch("core.json_store.upsert", return_value={"신규": 0, "갱신": 5})
    @patch("core.runner.run_site")
    def test_run_site_called_for_each_enabled_site(self, mock_run_site, mock_upsert):
        """활성화된 사이트마다 run_site가 한 번씩 호출되어야 한다."""
        mock_run_site.return_value = (
            [{"stable_id": "test-1", "공고명": "테스트"}],
            self._make_stat(),
        )

        run_once(MINIMAL_CONFIG)

        # g2b만 활성: run_site가 딱 1번 호출
        self.assertEqual(mock_run_site.call_count, 1)
        args, _ = mock_run_site.call_args
        self.assertEqual(args[0], "g2b")

    @patch("core.json_store.upsert", return_value={"신규": 0, "갱신": 5})
    @patch("core.runner.run_site")
    def test_run_site_called_for_multi_sites(self, mock_run_site, mock_upsert):
        """활성 사이트가 2개면 run_site가 2번 호출되어야 한다."""
        mock_run_site.return_value = ([], self._make_stat())

        run_once(MULTI_SITE_CONFIG)

        self.assertEqual(mock_run_site.call_count, 2)
        called_keys = [c.args[0] for c in mock_run_site.call_args_list]
        self.assertIn("g2b", called_keys)
        self.assertIn("nipa", called_keys)


# ──────────────────────────────────────────────────────────────
# 2. 자체 download_attachments 호출이 없는지 (정적 검사)
# ──────────────────────────────────────────────────────────────

class TestRunOnceNoDirectDownload(unittest.TestCase):
    """run_once() 소스코드 안에 download_attachments 직접 호출이 없는지 검증."""

    def test_no_download_attachments_in_run_once_source(self):
        """scheduler.run_once 소스에 download_attachments 호출이 없어야 한다."""
        import inspect
        from core.scheduler import run_once
        src = inspect.getsource(run_once)
        self.assertNotIn(
            "download_attachments",
            src,
            "run_once()에 download_attachments 직접 호출이 남아 있습니다 — runner에 위임해야 합니다.",
        )

    @patch("core.json_store.upsert", return_value={"신규": 0, "갱신": 5})
    @patch("core.runner.run_site", return_value=([], {"사이트": "나라장터", "수집": 0, "필터": 0, "첨부": 0, "오류": False}))
    @patch("core.downloader.download_attachments")
    def test_download_attachments_not_called_at_runtime(
        self, mock_dl, mock_run_site, mock_upsert
    ):
        """run_once() 실행 시 download_attachments가 호출되지 않는다."""
        run_once(MINIMAL_CONFIG)
        mock_dl.assert_not_called()


# ──────────────────────────────────────────────────────────────
# 3. json_upsert(저장) 호출 여부
# ──────────────────────────────────────────────────────────────

class TestRunOnceCallsUpsert(unittest.TestCase):
    """결과물이 있으면 json_upsert를 호출, 없으면 호출하지 않는지 검증."""

    def _stat(self, site="나라장터"):
        return {"사이트": site, "수집": 5, "필터": 5, "첨부": 0, "오류": False}

    @patch("core.json_store.upsert", return_value={"신규": 2, "갱신": 3})
    @patch("core.runner.run_site")
    def test_upsert_called_when_filtered_not_empty(self, mock_run_site, mock_upsert):
        """filtered 목록이 비어 있지 않으면 json_upsert를 호출해야 한다."""
        mock_run_site.return_value = (
            [{"stable_id": "x", "공고명": "A"}],
            self._stat(),
        )

        run_once(MINIMAL_CONFIG)

        mock_upsert.assert_called_once()

    @patch("core.json_store.upsert", return_value={"신규": 0, "갱신": 0})
    @patch("core.runner.run_site")
    def test_upsert_not_called_when_filtered_empty(self, mock_run_site, mock_upsert):
        """filtered 목록이 비어 있으면 json_upsert를 호출하지 않아야 한다."""
        mock_run_site.return_value = ([], self._stat())

        run_once(MINIMAL_CONFIG)

        mock_upsert.assert_not_called()


# ──────────────────────────────────────────────────────────────
# 4. 통계 집계가 올바른지
# ──────────────────────────────────────────────────────────────

class TestRunOnceSummaryAccumulation(unittest.TestCase):
    """복수 사이트의 신규/갱신 수치를 올바르게 합산하는지 검증."""

    @patch("core.json_store.upsert")
    @patch("core.runner.run_site")
    def test_stats_accumulate_across_sites(self, mock_run_site, mock_upsert):
        """각 사이트의 신규·갱신을 합산해서 최종 합계에 반영해야 한다."""
        # g2b → 신규 2, nipa → 신규 3
        upsert_calls = [{"신규": 2, "갱신": 0}, {"신규": 3, "갱신": 0}]
        mock_upsert.side_effect = upsert_calls

        stat_g2b = {"사이트": "나라장터", "수집": 5, "필터": 2, "첨부": 0, "오류": False}
        stat_nipa = {"사이트": "NIPA", "수집": 5, "필터": 3, "첨부": 0, "오류": False}

        records_g2b = [{"stable_id": "g-1"}, {"stable_id": "g-2"}]
        records_nipa = [{"stable_id": "n-1"}, {"stable_id": "n-2"}, {"stable_id": "n-3"}]

        mock_run_site.side_effect = [
            (records_g2b, stat_g2b),
            (records_nipa, stat_nipa),
        ]

        # _log_summary에 전달되는 total_new/total_update 값을 캡처
        with patch("core.scheduler._log_summary") as mock_log:
            run_once(MULTI_SITE_CONFIG)
            mock_log.assert_called_once()
            _, total_new, total_update = mock_log.call_args[0][1], mock_log.call_args[0][2], mock_log.call_args[0][3]
            # 총 신규 = 2 + 3 = 5
            self.assertEqual(total_new, 5)
            self.assertEqual(total_update, 0)


# ──────────────────────────────────────────────────────────────
# 5. _run_schedule이 run_once를 거치는지
# ──────────────────────────────────────────────────────────────

class TestRunScheduleUsesRunOnce(unittest.TestCase):
    """_run_schedule이 run_once를 통해 실행되는지 검증."""

    def test_schedule_registers_run_once(self):
        """_run_schedule 소스 코드 안에 run_once 호출이 있어야 한다."""
        import inspect
        from core.scheduler import _run_schedule
        src = inspect.getsource(_run_schedule)
        self.assertIn("run_once", src,
                      "_run_schedule이 run_once를 호출하지 않습니다.")


# ──────────────────────────────────────────────────────────────
# 6. enabled_site_keys 보조함수 동작
# ──────────────────────────────────────────────────────────────

class TestEnabledSiteKeys(unittest.TestCase):
    """enabled_site_keys()가 sources 설정을 올바르게 반환하는지 검증."""

    def test_returns_only_enabled_sites(self):
        cfg = {"sources": {"g2b": True, "nipa": False, "mss": True, "nia": False, "etri": False}}
        result = enabled_site_keys(cfg)
        self.assertIn("g2b", result)
        self.assertIn("mss", result)
        self.assertNotIn("nipa", result)
        self.assertNotIn("nia", result)
        self.assertNotIn("etri", result)

    def test_returns_empty_when_all_disabled(self):
        cfg = {"sources": {"g2b": False, "nipa": False, "mss": False, "nia": False, "etri": False}}
        result = enabled_site_keys(cfg)
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
