"""
공통 스크래퍼 추상 기반 클래스.
모든 사이트별 스크래퍼는 이 클래스를 상속하고 fetch_list / fetch_detail 을 구현한다.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional
import logging
import random
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

# 표준 공고 딕셔너리 키
ANNOUNCEMENT_KEYS = [
    "공고번호",
    "공고명",
    "발주기관",
    "출처사이트",
    "공고일",
    "마감일시",
    "예산금액",
    "내용요약",
    "첨부파일수",
    "첨부파일경로",
    "공고링크",
    "수집일시",
    # 내부 전달용 (Excel에는 저장하지 않음)
    "_attachment_urls",
]

_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def make_empty_announcement() -> dict:
    """빈 공고 딕셔너리를 반환한다."""
    return {
        "공고번호": "",
        "공고명": "",
        "발주기관": "",
        "출처사이트": "",
        "공고일": "",
        "마감일시": "",
        "예산금액": "",
        "내용요약": "",
        "첨부파일수": 0,
        "첨부파일경로": "",
        "공고링크": "",
        "수집일시": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "_attachment_urls": [],
    }


class BaseScraper(ABC):
    """사이트별 스크래퍼의 기반 클래스."""

    SOURCE_NAME: str = ""  # 서브클래스에서 반드시 오버라이드

    # True로 설정하면 runner.py가 PlaywrightBrowser를 생성해 주입한다.
    USE_PLAYWRIGHT_FOR_DETAIL: bool = False

    def __init__(self, config: dict):
        self.config = config
        req_cfg = config.get("request", {})
        self.timeout = req_cfg.get("timeout", 30)
        self.delay_min = req_cfg.get("delay_min", 1.0)
        self.delay_max = req_cfg.get("delay_max", 3.0)
        self.session = self._build_session(req_cfg.get("max_retries", 3))
        # runner.py에서 USE_PLAYWRIGHT_FOR_DETAIL=True일 때 주입된다.
        self.playwright_browser = None

    # ------------------------------------------------------------------
    # 추상 메서드 — 서브클래스 구현 필수
    # ------------------------------------------------------------------

    @abstractmethod
    def fetch_list(self) -> list[dict]:
        """
        공고 목록 페이지를 수집하여 공고 딕셔너리 리스트를 반환한다.
        페이지네이션을 처리해야 하며 각 항목은 최소한 아래 키를 채워야 한다:
          공고번호, 공고명, 발주기관, 공고일, 마감일시, 공고링크
        """

    @abstractmethod
    def fetch_detail(self, announcement: dict) -> dict:
        """
        공고 상세 페이지를 방문하여 announcement 딕셔너리에 누락된 필드를 채우고
        _attachment_urls 리스트에 첨부파일 URL을 추가한 뒤 반환한다.
        """

    # ------------------------------------------------------------------
    # 공개 메서드
    # ------------------------------------------------------------------

    def get_announcements(self) -> list[dict]:
        """
        전체 수집 플로우:
          1. fetch_list() 로 목록 수집
          2. 각 항목에 대해 fetch_detail() 로 상세 정보 보완
          3. 출처사이트, 수집일시 자동 설정
        """
        logger.info("[%s] 목록 수집 시작", self.SOURCE_NAME)
        try:
            items = self.fetch_list()
        except Exception as exc:
            logger.error("[%s] 목록 수집 실패: %s", self.SOURCE_NAME, exc)
            return []

        logger.info("[%s] 목록 %d건 수집됨, 상세 수집 시작", self.SOURCE_NAME, len(items))
        results: list[dict] = []
        for i, ann in enumerate(items, 1):
            ann.setdefault("출처사이트", self.SOURCE_NAME)
            ann.setdefault("수집일시", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
            ann.setdefault("_attachment_urls", [])
            try:
                ann = self.fetch_detail(ann)
            except Exception as exc:
                logger.warning(
                    "[%s] 상세 수집 실패 (%d/%d) %s: %s",
                    self.SOURCE_NAME, i, len(items), ann.get("공고링크", ""), exc,
                )
            results.append(ann)
            if i < len(items):
                self._sleep()

        logger.info("[%s] 상세 수집 완료 %d건", self.SOURCE_NAME, len(results))
        return results

    # ------------------------------------------------------------------
    # 내부 헬퍼
    # ------------------------------------------------------------------

    def _get_detail_html(self, url: str) -> str:
        """
        상세 페이지 HTML을 반환한다.
        USE_PLAYWRIGHT_FOR_DETAIL=True이고 playwright_browser가 주입되어 있으면
        Playwright로 JS 렌더링 후 반환하고, 아니면 requests를 사용한다.
        """
        if self.USE_PLAYWRIGHT_FOR_DETAIL and self.playwright_browser is not None:
            html = self.playwright_browser.get_html(url)
            if not html:
                logger.warning(
                    "[%s] Playwright 상세 페이지 빈 응답: %s", self.SOURCE_NAME, url
                )
            return html
        try:
            resp = self._get(url)
            return resp.text
        except Exception as exc:
            logger.warning(
                "[%s] 상세 페이지 요청 실패 %s: %s", self.SOURCE_NAME, url, exc
            )
            return ""

    def _get(self, url: str, **kwargs) -> requests.Response:
        """공용 GET 요청. 응답 인코딩을 자동으로 감지한다."""
        kwargs.setdefault("timeout", self.timeout)
        kwargs.setdefault("headers", _DEFAULT_HEADERS)
        resp = self.session.get(url, **kwargs)
        resp.raise_for_status()
        # 한국 사이트 중 일부는 Content-Type 인코딩 선언이 부정확하므로 apparent_encoding 사용
        if resp.encoding and resp.encoding.lower() in ("iso-8859-1", "latin-1"):
            resp.encoding = resp.apparent_encoding
        return resp

    def _sleep(self):
        """요청 간 랜덤 딜레이."""
        delay = random.uniform(self.delay_min, self.delay_max)
        time.sleep(delay)

    @staticmethod
    def _truncate(text: str, max_len: int = 300) -> str:
        """텍스트를 max_len 자로 자른다."""
        text = " ".join(text.split())  # 연속 공백/줄바꿈 정리
        return text[:max_len] if len(text) > max_len else text

    @staticmethod
    def _build_session(max_retries: int) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=max_retries,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET"],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        session.headers.update(_DEFAULT_HEADERS)
        return session
