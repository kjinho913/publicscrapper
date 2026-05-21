"""
한국전자통신연구원 (ETRI) 전자입찰 스크래퍼
URL: https://ebid.etri.re.kr/ebid/ebid/nSsEbidbulletinListPopup.do

목록: POST 방식 페이지네이션 (pageNo, biNo, pageLine 파라미터)
상세: POST 팝업 (nSsEbidInfoMainViewPopup.do) → 직접 접근 불가
python main.py --debug-etri 명령으로 원본 HTML 확인 가능.
"""

import logging
import re

from bs4 import BeautifulSoup

from .base import BaseScraper, make_empty_announcement

logger = logging.getLogger(__name__)

BASE_URL  = "https://ebid.etri.re.kr"
LIST_URL  = "https://ebid.etri.re.kr/ebid/ebid/nSsEbidbulletinListPopup.do"
PAGE_PARAM = "pageNo"
MAX_PAGES  = 5
SEL_ROWS   = "table tbody tr"


class EtriScraper(BaseScraper):
    SOURCE_NAME = "ETRI"

    def __init__(self, config: dict):
        super().__init__(config)
        _s = config.get("sites", {}).get("etri", {})
        self._list_url   = _s.get("list_url",  LIST_URL)
        self._page_param = _s.get("page_param", PAGE_PARAM)
        self._max_pages  = _s.get("max_pages",  MAX_PAGES)

    def fetch_list(self) -> list[dict]:
        results: list[dict] = []
        for page in range(1, self._max_pages + 1):
            items, has_next = self._fetch_page(page)
            results.extend(items)
            if not has_next or not items:
                break
            self._sleep()
        return results

    def _fetch_page(self, page: int) -> tuple[list[dict], bool]:
        data = {self._page_param: page, "biNo": "", "pageLine": 10}
        try:
            resp = self.session.post(self._list_url, data=data, timeout=self.timeout)
            resp.raise_for_status()
            resp.encoding = "euc-kr"
        except Exception as exc:
            logger.error("[ETRI] 목록 페이지 %d 실패: %s", page, exc)
            return [], False

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select(SEL_ROWS)
        if not rows:
            logger.warning("[ETRI] 목록 행을 찾지 못했습니다. HTML:\n%s", soup.prettify()[:2000])
            return [], False

        items = [ann for row in rows if (ann := self._parse_row(row))]
        return items, len(items) > 0

    def _parse_row(self, row) -> dict | None:
        tds = row.find_all("td")
        if len(tds) < 2:
            return None

        title = tds[1].get_text(strip=True)
        if not title:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME
        ann["공고명"] = title
        ann["발주기관"] = "ETRI"

        # 공고번호: 1열 텍스트, 없으면 onclick에서 추출
        bid_no = tds[0].get_text(strip=True)
        if not bid_no:
            m = re.search(r"nSsDetailViewPopup\('([^']+)'\)", row.get("onclick", ""))
            if m:
                bid_no = m.group(1)
        ann["공고번호"] = bid_no

        ann["공고일"]   = tds[3].get_text(strip=True) if len(tds) > 3 else ""

        deadline = tds[4].get_text(strip=True) if len(tds) > 4 else ""
        ann["마감일시"] = deadline if deadline != "~" else ""

        # 상세 URL은 POST 팝업이므로 목록 URL로 대체
        ann["공고링크"] = self._list_url

        return ann

    def fetch_detail(self, announcement: dict) -> dict:
        # 상세 페이지는 POST 팝업(nSsEbidInfoMainViewPopup.do)으로만 접근 가능
        # 첨부파일 수집 불가 → 목록 정보만 사용
        return announcement

    def debug_html(self):
        data = {self._page_param: 1, "biNo": "", "pageLine": 10}
        resp = self.session.post(self._list_url, data=data, timeout=self.timeout)
        resp.encoding = "euc-kr"
        print(f"\n=== ETRI 목록 페이지 HTML ===\n{resp.text[:5000]}")
