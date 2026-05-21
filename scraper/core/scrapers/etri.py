"""
한국전자통신연구원 (ETRI) 전자입찰 스크래퍼
URL: https://ebid.etri.re.kr/ebid/ebid/nSsEbidbulletinListPopup.do

목록: POST 방식 페이지네이션 (pageNo, biNo, pageLine 파라미터)
상세: POST 팝업 (nSsEbidInfoMainViewPopup.do) → 직접 접근 불가
python main.py --debug-etri 명령으로 원본 HTML 확인 가능.
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, make_empty_announcement

logger = logging.getLogger(__name__)

BASE_URL   = "https://ebid.etri.re.kr"
LIST_URL   = "https://ebid.etri.re.kr/ebid/ebid/nSsEbidbulletinListPopup.do"
DETAIL_URL = "https://ebid.etri.re.kr/ebid/ebid/nSsEbidInfoMainViewPopup.do"
PAGE_PARAM = "pageNo"
MAX_PAGES  = 5
SEL_ROWS   = "table tbody tr"


class EtriScraper(BaseScraper):
    SOURCE_NAME = "ETRI"
    USE_PLAYWRIGHT_FOR_DETAIL = True

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
        if self.playwright_browser is not None:
            html = self.playwright_browser.post_html(self._list_url, data)
            if not html:
                logger.error("[ETRI] 목록 페이지 %d 실패: Playwright post_html 반환값 없음", page)
                return [], False
        else:
            try:
                resp = self.session.post(self._list_url, data=data, timeout=self.timeout)
                resp.raise_for_status()
                resp.encoding = "euc-kr"
                html = resp.text
            except Exception as exc:
                logger.error("[ETRI] 목록 페이지 %d 실패: %s", page, exc)
                return [], False

        soup = BeautifulSoup(html, "lxml")
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

        # 상세 페이지는 POST 팝업 — 참조용 URL 설정
        ann["공고링크"] = f"{DETAIL_URL}?biNo={bid_no}" if bid_no else self._list_url

        return ann

    def fetch_detail(self, announcement: dict) -> dict:
        bid_no = announcement.get("공고번호", "")
        if not bid_no or self.playwright_browser is None:
            return announcement
        html = self.playwright_browser.post_html(DETAIL_URL, {"biNo": bid_no})
        if not html:
            return announcement
        soup = BeautifulSoup(html, "lxml")
        # 첨부파일 링크 추출
        for a in soup.select("a[href*='download'], a[href*='Down'], a[href*='file']"):
            href = a.get("href", "")
            if href and not href.startswith("javascript"):
                announcement["_attachment_urls"].append(urljoin(BASE_URL, href))
        # 내용 요약
        content_el = soup.select_one(".view_content, .bbs-content, table.tbl_view td")
        if content_el:
            announcement["내용요약"] = self._truncate(content_el.get_text(" ", strip=True))
        return announcement

    def debug_html(self):
        data = {self._page_param: 1, "biNo": "", "pageLine": 10}
        if self.playwright_browser is not None:
            html = self.playwright_browser.post_html(self._list_url, data)
        else:
            resp = self.session.post(self._list_url, data=data, timeout=self.timeout)
            resp.encoding = "euc-kr"
            html = resp.text
        print(f"\n=== ETRI 목록 페이지 HTML ===\n{html[:5000]}")
