"""
중소벤처기업부 (MSS) 스크래퍼
URL: https://www.mss.go.kr

[셀렉터 조정 안내]
브라우저로 https://www.mss.go.kr → 공지/공고 메뉴를 열고
F12 개발자도구에서 아래 상수들의 셀렉터를 확인 후 수정하세요.
python main.py --debug-mss 명령으로 원본 HTML 확인 가능.
"""

import logging
import re
from urllib.parse import urljoin, urlencode, urlparse, parse_qs

from bs4 import BeautifulSoup

from .base import BaseScraper, make_empty_announcement

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# [조정 필요]
# ─────────────────────────────────────────────────────────
BASE_URL  = "https://www.mss.go.kr"

# 사업공고(공고문) 게시판 URL — cbIdx=86(보도자료) 아님
LIST_URL  = "https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310"

PAGE_PARAM = "currentPage"
MAX_PAGES  = 5

SEL_ROWS       = "table tbody tr"
SEL_TITLE_LINK = "td.subject a, .title a, .board_subject a"
SEL_DATE       = "td:nth-child(4)"   # 번호/제목/첨부/날짜/조회 순서 (cbIdx=310 기준)
SEL_ORG        = "td.cd_subject"     # 접수처 컬럼 (cbIdx=310에 없음 → 발주기관 기본값 사용)
SEL_DEADLINE   = "td.end_date, .end_date, .deadline"
SEL_CONTENT    = ".view_content, .board_content, .bbs-content, .board-view-cont"
SEL_BUDGET     = ".budget, .price, td.price"
SEL_FILES      = "a[href*='/common/board/Download.do']"
# ─────────────────────────────────────────────────────────


class MssScraper(BaseScraper):
    SOURCE_NAME = "중소벤처기업부"
    USE_PLAYWRIGHT_FOR_DETAIL = True

    def __init__(self, config: dict):
        super().__init__(config)
        _s = config.get("sites", {}).get("mss", {})
        self._list_url  = _s.get("list_url",  LIST_URL)
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
        url = f"{self._list_url}&{self._page_param}={page}"
        try:
            resp = self._get(url)
        except Exception as exc:
            logger.error("[MSS] 목록 페이지 %d 실패: %s", page, exc)
            return [], False

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select(SEL_ROWS)
        if not rows:
            logger.warning(
                "[MSS] 목록 행을 찾지 못했습니다. 셀렉터(%s)를 확인하세요.\nHTML:\n%s",
                SEL_ROWS, soup.prettify()[:2000],
            )
            return [], False

        items = [ann for row in rows if (ann := self._parse_row(row))]
        return items, len(items) > 0

    def _parse_row(self, row) -> dict | None:
        title_el = row.select_one(SEL_TITLE_LINK)
        if not title_el:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME
        ann["공고명"] = title_el.get_text(strip=True)

        # onclick에서 cbIdx, bcIdx 추출 (href="#view"로 실제 URL이 없음)
        onclick = row.get("onclick", "") or title_el.get("onclick", "")
        m = re.search(r"doBbsFView\('(\d+)','(\d+)'", onclick)
        if m:
            href = f"/site/smba/ex/bbs/View.do?cbIdx={m.group(1)}&bcIdx={m.group(2)}"
        else:
            href = title_el.get("href", "")
        ann["공고링크"] = urljoin(BASE_URL, href)

        num_el = row.select_one("td.num, td:first-child, .num")
        ann["공고번호"] = (
            num_el.get_text(strip=True)
            if num_el
            else _extract_id(href)
        )

        date_el = row.select_one(SEL_DATE)
        ann["공고일"] = date_el.get_text(strip=True) if date_el else ""

        org_el = row.select_one(SEL_ORG)
        ann["발주기관"] = org_el.get_text(strip=True) if org_el else "중소벤처기업부"

        deadline_el = row.select_one(SEL_DEADLINE)
        ann["마감일시"] = deadline_el.get_text(strip=True) if deadline_el else ""
        return ann

    def fetch_detail(self, announcement: dict) -> dict:
        url = announcement.get("공고링크", "")
        if not url:
            return announcement
        html = self._get_detail_html(url)
        if not html:
            return announcement
        soup = BeautifulSoup(html, "lxml")

        content_el = soup.select_one(SEL_CONTENT)
        if content_el:
            announcement["내용요약"] = self._truncate(content_el.get_text(" ", strip=True))

        budget_el = soup.select_one(SEL_BUDGET)
        if budget_el:
            announcement["예산금액"] = _clean_amount(budget_el.get_text(strip=True))

        if not announcement["마감일시"]:
            announcement["마감일시"] = _extract_deadline(soup.get_text())

        for a in soup.select(SEL_FILES):
            href = a.get("href", "")
            if href:
                announcement["_attachment_urls"].append(urljoin(BASE_URL, href))

        return announcement

    def debug_html(self):
        resp = self._get(f"{self._list_url}&{self._page_param}=1")
        print(f"\n=== MSS 목록 페이지 HTML ===\n{resp.text[:5000]}")


def _extract_id(url: str) -> str:
    for key in ("bbsNttNo", "nttNo", "no", "id", "seq"):
        m = re.search(rf"[?&]{key}=(\w+)", url)
        if m:
            return m.group(1)
    m = re.search(r"/(\d+)/?$", url)
    return m.group(1) if m else url.split("/")[-1]


def _clean_amount(text: str) -> str:
    text = re.sub(r"[^\d,원억만천]", " ", text).strip()
    return text[:30]


def _extract_deadline(text: str) -> str:
    patterns = [
        r"마감[일시\s:：]*(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2})?)",
        r"(\d{4}[-./]\d{2}[-./]\d{2})\s*까지",
    ]
    for pat in patterns:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""
