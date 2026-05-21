"""
한국지능정보사회진흥원 (NIA) 스크래퍼
URL: https://www.nia.or.kr

실제 HTML 구조 (requests로 수집 가능 — SSR):
  <ul>
    <li>
      <a href="#view" onclick="doBbsFView('78336','29410','16010100','29410');return false;" title="제목">
        <span class="subject searchItem">제목</span>
        <span class="src">2026.05.19조회 139</span>
        <span class="writer">디지털접근성팀</span>
      </a>
    </li>
  </ul>
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, make_empty_announcement

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
BASE_URL   = "https://www.nia.or.kr"
LIST_URL   = "https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336"
PAGE_PARAM = "currentPage"
MAX_PAGES  = 5

SEL_ROWS       = "ul li"
SEL_TITLE_LINK = "a[onclick*='doBbsFView']"
SEL_FILES      = "a[href*='/common/board/Download.do']"
# ─────────────────────────────────────────────────────────


class NiaScraper(BaseScraper):
    SOURCE_NAME = "NIA"

    def __init__(self, config: dict):
        super().__init__(config)
        _s = config.get("sites", {}).get("nia", {})
        self._list_url   = _s.get("list_url",  LIST_URL)
        self._page_param = _s.get("page_param", PAGE_PARAM)
        self._max_pages  = _s.get("max_pages",  MAX_PAGES)

    def fetch_list(self) -> list[dict]:
        results: list[dict] = []
        seen_ids: set[str] = set()
        for page in range(1, self._max_pages + 1):
            items, has_next = self._fetch_page(page)
            if not items:
                break
            new_items = [a for a in items if a.get("공고번호", "") not in seen_ids]
            if not new_items:
                logger.info("[NIA] 페이지 %d — 새 항목 없음, 페이지네이션 종료", page)
                break
            for a in new_items:
                seen_ids.add(a.get("공고번호", ""))
            results.extend(new_items)
            if not has_next:
                break
            self._sleep()
        return results

    def _fetch_page(self, page: int) -> tuple[list[dict], bool]:
        url = f"{self._list_url}&{self._page_param}={page}"
        try:
            resp = self._get(url)
        except Exception as exc:
            logger.error("[NIA] 목록 페이지 %d 실패: %s", page, exc)
            return [], False

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select(SEL_ROWS)
        items = [ann for row in rows if (ann := self._parse_row(row))]
        if not items:
            logger.warning("[NIA] 목록 항목을 찾지 못했습니다. 셀렉터(%s)를 확인하세요.", SEL_TITLE_LINK)
            return [], False
        return items, True

    def _parse_row(self, row) -> dict | None:
        title_el = row.select_one(SEL_TITLE_LINK)
        if not title_el:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME

        # 제목: span.subject 또는 title 속성
        title_span = title_el.select_one("span.subject")
        ann["공고명"] = title_span.get_text(strip=True) if title_span else title_el.get("title", "")

        # URL + 공고번호: onclick="doBbsFView('cbIdx','bcIdx',...)"
        onclick = title_el.get("onclick", "")
        m = re.search(r"doBbsFView\('(\d+)','(\d+)'", onclick)
        if m:
            ann["공고링크"] = f"{BASE_URL}/site/nia_kor/ex/bbs/View.do?cbIdx={m.group(1)}&bcIdx={m.group(2)}"
            ann["공고번호"] = m.group(2)
        else:
            ann["공고링크"] = urljoin(BASE_URL, title_el.get("href", ""))
            ann["공고번호"] = _extract_id(ann["공고링크"])

        # 날짜: span.src = "2026.05.19조회 139"
        src_el = row.select_one("span.src")
        if src_el:
            m_date = re.search(r"\d{4}\.\d{2}\.\d{2}", src_el.get_text())
            ann["공고일"] = m_date.group(0) if m_date else ""

        # 작성기관
        writer_el = row.select_one("span.writer")
        ann["발주기관"] = writer_el.get_text(strip=True) if writer_el else "NIA"

        return ann

    def fetch_detail(self, announcement: dict) -> dict:
        url = announcement.get("공고링크", "")
        if not url:
            return announcement
        try:
            resp = self._get(url)
        except Exception as exc:
            logger.warning("[NIA] 상세 페이지 실패 %s: %s", url, exc)
            return announcement

        soup = BeautifulSoup(resp.text, "lxml")

        content_el = soup.select_one(".view_content, .board_content, .bbs-content")
        if content_el:
            announcement["내용요약"] = self._truncate(content_el.get_text(" ", strip=True))

        if not announcement["마감일시"]:
            announcement["마감일시"] = _extract_deadline(soup.get_text())

        for a in soup.select(SEL_FILES):
            href = a.get("href", "")
            if href:
                announcement["_attachment_urls"].append(urljoin(BASE_URL, href))

        return announcement

    def debug_html(self):
        resp = self._get(f"{self._list_url}&{self._page_param}=1")
        print(f"\n=== NIA 목록 페이지 HTML ===\n{resp.text[:5000]}")


def _extract_id(url: str) -> str:
    for key in ("bbsNttNo", "nttNo", "no", "id", "seq"):
        m = re.search(rf"[?&]{key}=(\w+)", url)
        if m:
            return m.group(1)
    m = re.search(r"/(\d+)/?$", url)
    return m.group(1) if m else url.split("/")[-1]


def _extract_deadline(text: str) -> str:
    for pat in [
        r"마감[일시\s:：]*(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2})?)",
        r"(\d{4}[-./]\d{2}[-./]\d{2})\s*까지",
    ]:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return ""
