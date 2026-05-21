"""
나라장터 (G2B) 스크래퍼 — 공공데이터포털 오픈API 기반
API: https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc

[API 키 설정]
config.yaml의 api_keys.g2b_api_key에 공공데이터포털 발급 키를 입력하세요.
발급: https://www.data.go.kr → 검색 "입찰공고정보" → 활용신청

API 응답 형식: XML
주요 파라미터:
  - numOfRows: 한 번에 가져올 건수 (최대 999)
  - pageNo: 페이지 번호
  - inqryBgnDt: 조회 시작일 (YYYYMMDD0000)
  - inqryEndDt: 조회 종료일 (YYYYMMDD2359)
  - bidClsfcNo: 입찰분류번호 (선택)
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from urllib.parse import urljoin

from .base import BaseScraper, make_empty_announcement

logger = logging.getLogger(__name__)

API_BASE = "https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc"
DETAIL_BASE = "https://www.g2b.go.kr/pt/menu/selectSubFrame.do"
NUM_OF_ROWS = 100
MAX_PAGES = 10   # 최대 1,000건


class G2bScraper(BaseScraper):
    SOURCE_NAME = "나라장터"

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_keys", {}).get("g2b_api_key", "")
        if not self.api_key or self.api_key == "YOUR_DATA_GO_KR_API_KEY":
            logger.warning(
                "[G2B] API 키가 설정되지 않았습니다. config.yaml의 api_keys.g2b_api_key를 설정하세요."
            )
        _s = config.get("sites", {}).get("g2b", {})
        self._api_base       = _s.get("api_base",       API_BASE)
        self._max_pages      = _s.get("max_pages",      MAX_PAGES)
        self._date_range_days = _s.get("date_range_days", 7)

    def fetch_list(self) -> list[dict]:
        if not self.api_key or self.api_key == "YOUR_DATA_GO_KR_API_KEY":
            logger.error("[G2B] API 키 없음, 건너뜀")
            return []

        today = datetime.now()
        start = (today - timedelta(days=self._date_range_days)).strftime("%Y%m%d") + "0000"
        end   = today.strftime("%Y%m%d") + "2359"

        results: list[dict] = []
        for page in range(1, self._max_pages + 1):
            items, total = self._fetch_page(page, start, end)
            results.extend(items)
            logger.debug("[G2B] 페이지 %d: %d건 (전체 %d건)", page, len(items), total)
            if len(results) >= total or not items:
                break
            self._sleep()

        return results

    def _fetch_page(self, page: int, start: str, end: str) -> tuple[list[dict], int]:
        params = {
            "serviceKey": self.api_key,
            "numOfRows": NUM_OF_ROWS,
            "pageNo": page,
            "type": "xml",
            "inqryBgnDt": start,
            "inqryEndDt": end,
            "inqryDiv": 1,
        }
        try:
            resp = self._get(self._api_base, params=params)
        except Exception as exc:
            logger.error("[G2B] API 요청 실패 (페이지 %d): %s", page, exc)
            return [], 0

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error("[G2B] XML 파싱 실패: %s\n응답: %s", exc, resp.text[:500])
            return [], 0

        # 에러 코드 확인
        result_code = _xml_text(root, ".//resultCode")
        if result_code and result_code != "00":
            result_msg = _xml_text(root, ".//resultMsg")
            logger.error("[G2B] API 오류 %s: %s", result_code, result_msg)
            return [], 0

        total_count = int(_xml_text(root, ".//totalCount") or "0")
        items_el = root.findall(".//item")

        announcements: list[dict] = []
        for item in items_el:
            ann = self._parse_item(item)
            if ann:
                announcements.append(ann)

        return announcements, total_count

    def _parse_item(self, item) -> dict | None:
        bid_no = _xml_text(item, "bidNtceNo")
        title = _xml_text(item, "bidNtceNm")
        if not title:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME
        ann["공고번호"] = bid_no or ""
        ann["공고명"] = title

        # 발주기관
        ann["발주기관"] = (
            _xml_text(item, "dminsttNm")
            or _xml_text(item, "ntceInsttNm")
            or "나라장터"
        )

        # 공고일 (YYYYMMDD → YYYY-MM-DD)
        reg_date = _xml_text(item, "bidNtceDt") or _xml_text(item, "rgstDt") or ""
        ann["공고일"] = _format_date(reg_date)

        # 마감일시
        deadline = _xml_text(item, "bidClseDateTime") or _xml_text(item, "opengDateTime") or ""
        ann["마감일시"] = _format_datetime(deadline)

        # 예산금액
        budget = _xml_text(item, "asignBdgtAmt") or _xml_text(item, "presmptPrce") or ""
        if budget:
            try:
                ann["예산금액"] = f"{int(float(budget)):,}"
            except ValueError:
                ann["예산금액"] = budget

        # 공고 링크 (나라장터 상세 페이지)
        ann["공고링크"] = _build_detail_url(bid_no)

        # 내용요약 (API에 없는 경우 공고명으로 대체)
        ann["내용요약"] = _xml_text(item, "dtlBidNtceNm") or title

        # 카테고리코드 (필터링용, Excel에는 저장 안 함)
        ann["카테고리코드"] = _xml_text(item, "bidClsfcNo") or ""

        return ann

    def fetch_detail(self, announcement: dict) -> dict:
        # G2B API는 이미 상세 정보를 제공하므로
        # 첨부파일 URL은 상세 페이지 HTML에서 추출
        url = announcement.get("공고링크", "")
        if not url:
            return announcement
        try:
            resp = self._get(url)
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(resp.text, "lxml")
            for a in soup.select("a[href*='download'], a[href*='fileDown'], .atch a"):
                href = a.get("href", "")
                if href:
                    announcement["_attachment_urls"].append(
                        urljoin("https://www.g2b.go.kr", href)
                    )
        except Exception as exc:
            logger.debug("[G2B] 상세 페이지 첨부파일 수집 실패 %s: %s", url, exc)
        return announcement


# ─── 헬퍼 함수 ────────────────────────────────────────────

def _xml_text(element, tag: str) -> str:
    el = element.find(tag)
    return el.text.strip() if el is not None and el.text else ""


def _format_date(s: str) -> str:
    """YYYYMMDD → YYYY-MM-DD"""
    s = re.sub(r"[^\d]", "", s)
    if len(s) >= 8:
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s


def _format_datetime(s: str) -> str:
    """YYYYMMDDHHMM 또는 YYYY-MM-DD HH:MM → YYYY-MM-DD HH:MM"""
    s_clean = re.sub(r"[^\d]", "", s)
    if len(s_clean) >= 12:
        return f"{s_clean[:4]}-{s_clean[4:6]}-{s_clean[6:8]} {s_clean[8:10]}:{s_clean[10:12]}"
    if len(s_clean) >= 8:
        return f"{s_clean[:4]}-{s_clean[4:6]}-{s_clean[6:8]}"
    return s


def _build_detail_url(bid_no: str) -> str:
    if not bid_no:
        return ""
    return (
        f"https://www.g2b.go.kr/pt/menu/selectSubFrame.do"
        f"?framesrc=/pt/menu/frameTgong.do"
        f"?bidNtceNo={bid_no}"
    )
