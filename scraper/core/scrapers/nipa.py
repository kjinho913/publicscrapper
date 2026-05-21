"""
정보통신산업진흥원 (NIPA) 스크래퍼
URL: https://www.nipa.kr

[셀렉터 조정 안내]
실제 실행 전 브라우저로 https://www.nipa.kr 에서 사업공고 게시판을 열고,
F12 개발자도구로 아래 상수들의 CSS 셀렉터를 확인 후 수정하세요.
python main.py --debug-nipa 명령으로 원본 HTML을 출력해 확인할 수 있습니다.
"""

import logging
import re
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .base import BaseScraper, make_empty_announcement

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────
# [조정 필요] 사이트 구조에 맞게 수정하세요
# ─────────────────────────────────────────────────────────
BASE_URL = "https://www.nipa.kr"

# 사업공고 게시판 URL (브라우저에서 실제 URL 확인 필요)
LIST_URL = "https://www.nipa.kr/home/bsnsAll/0/nttList?bbsNo=4&bsnsDtlsIemNo=&tab=2"

# 목록 페이지 파라미터 (페이지네이션)
PAGE_PARAM = "curPage"       # URL 쿼리스트링의 페이지 파라미터 이름
MAX_PAGES  = 5               # 최대 수집 페이지 수 (너무 많으면 부하 증가)

# 목록 페이지 CSS 셀렉터
SEL_ROWS       = "table.tbgg tbody tr"                                               # 공고 행
SEL_TITLE_LINK = "a[href*='nttDetail'], td.subject a, .title a, .board-subject a"   # 제목 링크
SEL_DATE       = "td:nth-child(4), td.date, .date, .reg-date"                       # 게재일 (4번째 컬럼)
SEL_ORG        = "td:nth-child(3), td.writer, .writer, .department"                 # 기관/부서명 (3번째 컬럼)
SEL_DEADLINE   = "td:nth-child(1), td.end_date, .end-date, .deadline"               # D-xx 마감 표시

# 상세 페이지 CSS 셀렉터
SEL_CONTENT    = ".view_content, .board-content, .bbs-content, .view-cont"
SEL_BUDGET     = ".budget, .price, .contract-price"            # 예산 (없으면 빈 값)
SEL_FILES      = "a[href*='/comm/getFile']"
# ─────────────────────────────────────────────────────────


class NipaScraper(BaseScraper):
    SOURCE_NAME = "NIPA"
    USE_PLAYWRIGHT_FOR_DETAIL = True

    def __init__(self, config: dict):
        super().__init__(config)
        _s = config.get("sites", {}).get("nipa", {})
        self._list_url   = _s.get("list_url",  LIST_URL)
        self._page_param = _s.get("page_param", PAGE_PARAM)
        self._max_pages  = _s.get("max_pages",  MAX_PAGES)

    def fetch_list(self) -> list[dict]:
        results: list[dict] = []
        for page in range(1, self._max_pages + 1):
            items, has_next = self._fetch_page(page)
            results.extend(items)
            logger.debug("[NIPA] 페이지 %d: %d건 수집", page, len(items))
            if not has_next or not items:
                break
            self._sleep()
        return results

    def _fetch_page(self, page: int) -> tuple[list[dict], bool]:
        url = f"{self._list_url}&{self._page_param}={page}"
        try:
            resp = self._get(url)
        except Exception as exc:
            logger.error("[NIPA] 목록 페이지 %d 요청 실패: %s", page, exc)
            return [], False

        soup = BeautifulSoup(resp.text, "lxml")
        rows = soup.select(SEL_ROWS)
        if not rows:
            # 셀렉터가 맞지 않을 때를 대비한 디버그 출력
            logger.warning(
                "[NIPA] 목록 행을 찾지 못했습니다. 셀렉터(%s)를 확인하세요.\n"
                "HTML 일부:\n%s",
                SEL_ROWS,
                soup.prettify()[:2000],
            )
            return [], False

        items: list[dict] = []
        for row in rows:
            ann = self._parse_row(row)
            if ann:
                items.append(ann)

        # 다음 페이지 존재 여부: 현재 페이지 행이 0이면 마지막으로 판단
        has_next = len(items) > 0
        return items, has_next

    def _parse_row(self, row) -> dict | None:
        title_el = row.select_one(SEL_TITLE_LINK)
        if not title_el:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME
        ann["공고명"] = title_el.get_text(strip=True)

        # 상세 링크 (./nttDetail?... 형태의 상대 경로이므로 list_url을 기준으로 resolve)
        href = title_el.get("href", "")
        ann["공고링크"] = urljoin(self._list_url, href)

        # 공고번호: URL에서 추출하거나 행 번호 셀에서 읽음
        num_el = row.select_one("td.num, td:first-child, .num")
        ann["공고번호"] = (
            num_el.get_text(strip=True)
            if num_el
            else _extract_id_from_url(href)
        )

        # 게재일
        date_el = row.select_one(SEL_DATE)
        ann["공고일"] = date_el.get_text(strip=True) if date_el else ""

        # 기관명
        org_el = row.select_one(SEL_ORG)
        ann["발주기관"] = org_el.get_text(strip=True) if org_el else "NIPA"

        # 마감일 (목록에 없으면 상세에서 보완)
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

        # 내용 요약
        content_el = soup.select_one(SEL_CONTENT)
        if content_el:
            announcement["내용요약"] = self._truncate(content_el.get_text(" ", strip=True))

        # 예산
        budget_el = soup.select_one(SEL_BUDGET)
        if budget_el:
            announcement["예산금액"] = _clean_amount(budget_el.get_text(strip=True))

        # 마감일 (목록에서 못 얻었을 경우 상세에서 재시도)
        if not announcement["마감일시"]:
            announcement["마감일시"] = _extract_deadline_from_text(soup.get_text())

        # 첨부파일 URL 수집
        file_links = soup.select(SEL_FILES)
        for a in file_links:
            href = a.get("href", "")
            if href:
                announcement["_attachment_urls"].append(urljoin(BASE_URL, href))

        return announcement

    def debug_html(self):
        """셀렉터 조정용: 목록 1페이지 원본 HTML을 출력한다."""
        resp = self._get(f"{self._list_url}&{self._page_param}=1")
        print(f"\n=== NIPA 목록 페이지 HTML ({self._list_url}) ===")
        print(resp.text[:5000])


# ─── 헬퍼 함수 ────────────────────────────────────────────

def _extract_id_from_url(url: str) -> str:
    """URL 쿼리스트링이나 경로에서 공고 ID를 추출한다."""
    for key in ("nttNo", "bbsNttNo", "no", "id", "seq"):
        m = re.search(rf"[?&]{key}=(\d+)", url)
        if m:
            return m.group(1)
    # 경로 끝 숫자
    m = re.search(r"/(\d+)/?$", url)
    return m.group(1) if m else url.split("?")[0].rstrip("/").split("/")[-1]


def _clean_amount(text: str) -> str:
    """'금액' 등의 레이블을 제거하고 숫자만 남긴다."""
    text = re.sub(r"[^\d,원]", " ", text).strip()
    return text[:30]


def _extract_deadline_from_text(full_text: str) -> str:
    """본문 텍스트에서 마감일 패턴을 찾는다."""
    patterns = [
        r"마감[일시\s:：]*(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2})?)",
        r"접수\s*마감[일시\s:：]*(\d{4}[-./]\d{2}[-./]\d{2}(?:\s+\d{2}:\d{2})?)",
        r"(\d{4}[-./]\d{2}[-./]\d{2})\s*까지",
    ]
    for pat in patterns:
        m = re.search(pat, full_text)
        if m:
            return m.group(1).strip()
    return ""
