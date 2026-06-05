"""
나라장터 (G2B) 스크래퍼 v1.0 — PPSSrch 검색어 기반 수집
API 기반: 공공데이터포털 오픈API

[수집 단계]
  - 입찰공고: getBidPblancListInfoServcPPSSrch  (bidNtceNm 파라미터로 서버 검색)
  - 사전규격: getPublicPrcureThngInfoServcPPSSrch (prdctClsfcNoNm 파라미터로 서버 검색)

[API 키 설정]
  scraper/.env 파일에 G2B_API_KEY=<발급키> 형태로 입력하세요.
  발급: https://www.data.go.kr → "입찰공고정보" 또는 "사전규격정보" 검색 → 활용신청

[검증된 API 응답 필드 (2026-06-02 실제 호출 확인)]
  입찰공고 PPSSrch:
    공고번호    : bidNtceNo
    공고명      : bidNtceNm
    발주기관    : dminsttNm / ntceInsttNm
    공고일      : bidNtceDt
    마감일시    : bidClseDt
    예산금액    : asignBdgtAmt
    공고링크    : bidNtceDtlUrl
    첨부파일    : ntceSpecDocUrl1 ~ ntceSpecDocUrl10
    계약방법    : cntrctCnclsMthdNm  (필터 전용)
    낙찰방법    : sucsfbidMthdNm     (필터 전용, 복합 문자열 "협상에의한계약-...")

  사전규격 PPSSrch:
    규격번호    : refNo
    품명        : prdctClsfcNoNm
    발주기관    : orderInsttNm / rlDminsttNm
    등록일      : rcptDt
    마감일시    : opninRgstClseDt
    예산금액    : asignBdgtAmt
    공고링크    : 필드 없음 → bfSpecRgstNo로 직접 URL 구성
    첨부파일    : specDocFileUrl1 ~ specDocFileUrl5  (입찰공고와 다른 필드명)
    계약/낙찰방법: 없음 (사전규격 단계이므로 미결정)
"""

import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta

from .base import BaseScraper, make_empty_announcement
from core.ids import derive_stable_id

logger = logging.getLogger(__name__)

# ── API 엔드포인트 ─────────────────────────────────────────────────────────
BID_NOTICE_URL = (
    "https://apis.data.go.kr/1230000/ad/BidPublicInfoService"
    "/getBidPblancListInfoServcPPSSrch"
)
PRE_STANDARD_URL = (
    "https://apis.data.go.kr/1230000/ao/HrcspSsstndrdInfoService"
    "/getPublicPrcureThngInfoServcPPSSrch"
)
# 사전규격 상세 링크 — bfSpecRgstNo로 직접 URL 구성
PRE_STANDARD_DETAIL_BASE = "https://www.g2b.go.kr/pn/pnz/pnza/pubPrcureThng/detail.do?bfSpecRegNo={bfSpecRgstNo}"

NUM_OF_ROWS = 100   # 페이지당 최대 100건
MAX_PAGES = 10      # 페이지네이션 최대 10페이지 (최대 1,000건)

# 나라장터 API 1회 조회 기간 상한 — 보수적으로 30일로 설정.
# --days 값이 이 한계를 초과하면 자동으로 청크 분할 조회함.
_CHUNK_DAYS = 30


class G2bScraper(BaseScraper):
    SOURCE_NAME = "나라장터"
    USE_PLAYWRIGHT_FOR_DETAIL = False
    FETCH_DETAIL = False  # 모든 데이터를 API 응답에서 직접 수집

    def __init__(self, config: dict):
        super().__init__(config)
        self.api_key = config.get("api_keys", {}).get("g2b_api_key", "")
        if not self.api_key:
            logger.warning(
                "[G2B] API 키가 설정되지 않았습니다. "
                "scraper/.env 파일에 G2B_API_KEY를 입력하세요."
            )
        g2b_cfg = config.get("sites", {}).get("g2b", {})
        stages = g2b_cfg.get("stages", {})
        self._do_bid_notice   = stages.get("bid_notice",   True)
        self._do_pre_standard = stages.get("pre_standard", True)
        self._date_range_days = g2b_cfg.get("date_range_days", 3)
        self._search_keywords: list[str] = g2b_cfg.get("search_keywords", [])

    # ──────────────────────────────────────────────────────────────────────
    # 공개 인터페이스
    # ──────────────────────────────────────────────────────────────────────

    def fetch_list(self) -> list[dict]:
        """키워드 × 단계 × 날짜 청크 조합으로 PPSSrch를 호출하고, 중복을 제거해 반환한다.

        date_range_days가 _CHUNK_DAYS(30일)를 초과하면 30일 단위 구간으로 분할해
        각 구간을 별도 API 호출로 처리한다. 청크 간 중복은 _deduplicate()가 처리하므로
        경계 겹침이 있어도 무방하다.
        """
        if not self.api_key:
            logger.error("[G2B] API 키 없음, 건너뜀")
            return []

        # ★ 검색어 최소 1개 필수 (planner 확정 사항)
        if not self._search_keywords:
            logger.error(
                "[G2B] search_keywords가 비어 있습니다. "
                "config.yaml → sites.g2b.search_keywords에 키워드를 1개 이상 입력하세요. "
                "수집을 중단합니다."
            )
            return []

        # 날짜 청크 목록 생성 — date_range_days가 _CHUNK_DAYS 이하면 청크 1개
        chunks = _build_date_chunks(self._date_range_days, _CHUNK_DAYS)
        if len(chunks) > 1:
            logger.info(
                "[G2B] 수집 기간 %d일 → %d개 청크로 분할 (청크당 최대 %d일)",
                self._date_range_days, len(chunks), _CHUNK_DAYS,
            )

        all_items: list[dict] = []

        for chunk_idx, (start, end) in enumerate(chunks, start=1):
            chunk_label = f"청크{chunk_idx}/{len(chunks)} ({start[:8]}~{end[:8]})"

            if self._do_bid_notice:
                logger.info("[G2B] 입찰공고 수집 시작 (키워드 %d개, %s)", len(self._search_keywords), chunk_label)
                for kw in self._search_keywords:
                    items = self._fetch_stage_all_pages(
                        url=BID_NOTICE_URL,
                        search_param="bidNtceNm",
                        keyword=kw,
                        start=start,
                        end=end,
                        parser=self._parse_bid_item,
                        stage_label="입찰공고",
                    )
                    all_items.extend(items)

            if self._do_pre_standard:
                logger.info("[G2B] 사전규격 수집 시작 (키워드 %d개, %s)", len(self._search_keywords), chunk_label)
                for kw in self._search_keywords:
                    items = self._fetch_stage_all_pages(
                        url=PRE_STANDARD_URL,
                        search_param="prdctClsfcNoNm",
                        keyword=kw,
                        start=start,
                        end=end,
                        parser=self._parse_prestandard_item,
                        stage_label="사전규격",
                    )
                    all_items.extend(items)

        # (공고번호, 단계) 기준 중복 제거 — 같은 공고를 여러 키워드/청크에서 잡았을 때 처리
        deduped = _deduplicate(all_items)
        logger.info(
            "[G2B] 합산 %d건 → 중복제거 후 %d건",
            len(all_items), len(deduped),
        )
        return deduped

    def fetch_detail(self, announcement: dict) -> dict:
        # 첨부파일/링크를 API 응답에서 직접 수집하므로 추가 처리 불필요
        return announcement

    # ──────────────────────────────────────────────────────────────────────
    # 내부 — 페이지네이션 처리
    # ──────────────────────────────────────────────────────────────────────

    def _fetch_stage_all_pages(
        self,
        url: str,
        search_param: str,
        keyword: str,
        start: str,
        end: str,
        parser,
        stage_label: str,
    ) -> list[dict]:
        """단일 키워드에 대해 전 페이지를 순회하며 수집한다."""
        results: list[dict] = []
        for page in range(1, MAX_PAGES + 1):
            items, total = self._fetch_one_page(
                url=url,
                search_param=search_param,
                keyword=keyword,
                start=start,
                end=end,
                page=page,
                parser=parser,
                stage_label=stage_label,
            )
            results.extend(items)
            logger.debug(
                "[G2B][%s] 키워드='%s' 페이지%d: %d건 (전체 %d건)",
                stage_label, keyword, page, len(items), total,
            )
            if not items or len(results) >= total:
                break
            self._sleep()
        return results

    def _fetch_one_page(
        self,
        url: str,
        search_param: str,
        keyword: str,
        start: str,
        end: str,
        page: int,
        parser,
        stage_label: str,
    ) -> tuple[list[dict], int]:
        """단일 페이지를 호출해 파싱 결과와 전체 건수를 반환한다."""
        params = {
            "serviceKey": self.api_key,
            "numOfRows": NUM_OF_ROWS,
            "pageNo": page,
            "type": "xml",
            "inqryDiv": 1,
            "inqryBgnDt": start,
            "inqryEndDt": end,
            search_param: keyword,
        }
        try:
            resp = self._get(url, params=params)
        except Exception as exc:
            logger.error("[G2B][%s] API 요청 실패 (페이지 %d): %s", stage_label, page, exc)
            return [], 0

        try:
            root = ET.fromstring(resp.content)
        except ET.ParseError as exc:
            logger.error(
                "[G2B][%s] XML 파싱 실패: %s\n응답: %s",
                stage_label, exc, resp.text[:300],
            )
            return [], 0

        result_code = _xml_text(root, ".//resultCode")
        if result_code and result_code != "00":
            result_msg = _xml_text(root, ".//resultMsg")
            logger.error("[G2B][%s] API 오류 %s: %s", stage_label, result_code, result_msg)
            return [], 0

        total_count = int(_xml_text(root, ".//totalCount") or "0")
        announcements: list[dict] = []
        for item_el in root.findall(".//item"):
            ann = parser(item_el)
            if ann:
                announcements.append(ann)

        return announcements, total_count

    # ──────────────────────────────────────────────────────────────────────
    # 내부 — 단계별 파서 (스키마가 서로 다름)
    # ──────────────────────────────────────────────────────────────────────

    def _parse_bid_item(self, item) -> dict | None:
        """입찰공고 PPSSrch 응답 아이템 → 표준 공고 딕셔너리."""
        bid_no = _xml_text(item, "bidNtceNo")
        title  = _xml_text(item, "bidNtceNm")
        if not title:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME
        ann["공고번호"]   = bid_no or ""
        ann["공고명"]     = title

        ann["발주기관"] = (
            _xml_text(item, "dminsttNm")
            or _xml_text(item, "ntceInsttNm")
            or "나라장터"
        )

        # 공고일: bidNtceDt 는 "YYYY-MM-DD HH:MM:SS" 형태로 옴
        ann["공고일"]   = _format_date(_xml_text(item, "bidNtceDt"))
        # 마감일시: bidClseDt
        ann["마감일시"] = _format_datetime(_xml_text(item, "bidClseDt"))

        # 예산금액
        budget = _xml_text(item, "asignBdgtAmt")
        ann["예산금액"] = _format_budget(budget)

        # 공고 링크
        ann["공고링크"] = _xml_text(item, "bidNtceDtlUrl") or _xml_text(item, "bidNtceUrl") or ""

        # 내용요약 (API에 별도 설명 필드 없으므로 공고명 사용)
        ann["내용요약"] = title

        # 첨부파일 URL (ntceSpecDocUrl1~10)
        for i in range(1, 11):
            url = _xml_text(item, f"ntceSpecDocUrl{i}")
            if url:
                ann["_attachment_urls"].append(url)

        # 저장소 공개 필드
        ann["단계"]      = "입찰공고"
        ann["stable_id"] = derive_stable_id(self.SOURCE_NAME, ann["공고링크"])

        # 필터 전용 필드 (저장하지 않음)
        ann["_단계"]     = "입찰공고"
        ann["_계약방법"] = _xml_text(item, "cntrctCnclsMthdNm")
        ann["_낙찰방법"] = _xml_text(item, "sucsfbidMthdNm")
        ann["_예산금액"] = _parse_int(budget)  # 정수 (필터 비교용)

        return ann

    def _parse_prestandard_item(self, item) -> dict | None:
        """사전규격 PPSSrch 응답 아이템 → 표준 공고 딕셔너리."""
        ref_no = _xml_text(item, "refNo")
        title  = _xml_text(item, "prdctClsfcNoNm")  # 품명 = 사전규격의 공고명
        if not title:
            return None

        ann = make_empty_announcement()
        ann["출처사이트"] = self.SOURCE_NAME
        ann["공고번호"]   = ref_no or ""
        ann["공고명"]     = title

        ann["발주기관"] = (
            _xml_text(item, "orderInsttNm")
            or _xml_text(item, "rlDminsttNm")
            or "나라장터"
        )

        # 공고일: rcptDt (등록일)
        ann["공고일"]   = _format_date(_xml_text(item, "rcptDt"))
        # 마감일시: opninRgstClseDt (의견등록마감)
        ann["마감일시"] = _format_datetime(_xml_text(item, "opninRgstClseDt"))

        # 예산금액
        budget = _xml_text(item, "asignBdgtAmt")
        ann["예산금액"] = _format_budget(budget)

        # 공고 링크: 사전규격은 bidNtceDtlUrl 없음 → bfSpecRgstNo로 직접 구성
        bfsrn = _xml_text(item, "bfSpecRgstNo")
        if bfsrn:
            ann["공고링크"] = PRE_STANDARD_DETAIL_BASE.format(bfSpecRgstNo=bfsrn)
        else:
            ann["공고링크"] = ""

        # 내용요약
        ann["내용요약"] = title

        # 첨부파일 URL (specDocFileUrl1~5 — 입찰공고와 다른 필드명)
        for i in range(1, 6):
            url = _xml_text(item, f"specDocFileUrl{i}")
            if url:
                ann["_attachment_urls"].append(url)

        # 저장소 공개 필드
        ann["단계"]      = "사전규격"
        ann["stable_id"] = derive_stable_id(self.SOURCE_NAME, ann["공고링크"])

        # 필터 전용 필드 — 사전규격은 계약/낙찰방법이 미결정 단계라 빈 값
        ann["_단계"]     = "사전규격"
        ann["_계약방법"] = ""
        ann["_낙찰방법"] = ""
        ann["_예산금액"] = _parse_int(budget)

        return ann


# ── 헬퍼 함수 ────────────────────────────────────────────────────────────

def _build_date_chunks(total_days: int, chunk_days: int) -> list[tuple[str, str]]:
    """오늘 기준 total_days 전부터 오늘까지의 기간을 chunk_days 단위 구간 목록으로 반환한다.

    각 구간은 ("YYYYMMDDHHMM", "YYYYMMDDHHMM") 형식의 튜플.
    구간은 오래된 날짜에서 최신 날짜 순으로 정렬된다.
    total_days <= chunk_days 이면 구간이 1개만 반환된다.

    예) total_days=90, chunk_days=30 → 3개 구간
        [(61일전~31일전), (31일전~1일전), (1일전~오늘)]
    """
    today = datetime.now()
    chunks: list[tuple[str, str]] = []

    # chunk_start_days: 현재 청크의 시작 오프셋 (오늘 기준 며칠 전인지)
    chunk_start_days = total_days

    while chunk_start_days > 0:
        chunk_end_days = chunk_start_days - chunk_days
        if chunk_end_days < 0:
            chunk_end_days = 0

        start_dt = today - timedelta(days=chunk_start_days)
        end_dt   = today - timedelta(days=chunk_end_days)

        start_str = start_dt.strftime("%Y%m%d") + "0000"
        end_str   = end_dt.strftime("%Y%m%d") + "2359"

        chunks.append((start_str, end_str))
        chunk_start_days = chunk_end_days

    return chunks


def _deduplicate(items: list[dict]) -> list[dict]:
    """(공고번호, _단계) 기준으로 중복을 제거한다. 먼저 나온 항목을 유지."""
    seen: set[tuple] = set()
    result: list[dict] = []
    for item in items:
        key = (item.get("공고번호", ""), item.get("_단계", ""))
        if key not in seen:
            seen.add(key)
            result.append(item)
    return result


def _xml_text(element, tag: str) -> str:
    el = element.find(tag)
    return el.text.strip() if el is not None and el.text else ""


def _format_date(s: str) -> str:
    """YYYYMMDD 또는 YYYY-MM-DD HH:MM:SS → YYYY-MM-DD"""
    digits = re.sub(r"[^\d]", "", s)
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s


def _format_datetime(s: str) -> str:
    """YYYYMMDDHHMM 또는 YYYY-MM-DD HH:MM(:SS) → YYYY-MM-DD HH:MM"""
    digits = re.sub(r"[^\d]", "", s)
    if len(digits) >= 12:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]} {digits[8:10]}:{digits[10:12]}"
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return s


def _format_budget(raw: str) -> str:
    """예산 금액 문자열을 천 단위 쉼표 형식으로 변환한다."""
    if not raw:
        return ""
    try:
        return f"{int(float(raw)):,}"
    except (ValueError, TypeError):
        return raw


def _parse_int(raw: str) -> int | None:
    """예산 문자열을 정수로 변환한다. 변환 불가 시 None."""
    if not raw:
        return None
    try:
        return int(float(raw))
    except (ValueError, TypeError):
        return None
