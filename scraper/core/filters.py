"""
키워드 + 카테고리 필터링 모듈.
config.yaml의 filters 섹션을 기반으로 공고의 포함 여부를 판별한다.

함수 목록:
  matches()     — nipa/nia/mss/etri 등 기존 사이트 공통 필터 (변경 없음)
  refine_g2b()  — 나라장터 전용 정제 필터 (v1.0 신설)
"""

import logging

logger = logging.getLogger(__name__)


def matches(announcement: dict, cfg: dict) -> bool:
    """
    공고가 필터 조건에 해당하는지 판별한다.

    Args:
        announcement: 표준 공고 딕셔너리.
        cfg: config["filters"] 섹션 딕셔너리 (사이트별 오버라이드 병합 후).

    Returns:
        True면 수집 대상, False면 건너뜀.
    """
    keywords: list[str] = cfg.get("keywords", [])
    exclude_keywords: list[str] = cfg.get("exclude_keywords", [])
    categories: list[str] = [str(c) for c in cfg.get("categories", [])]
    logic: str = cfg.get("match_logic", "OR").upper()

    # 제외 키워드: 하나라도 매칭되면 즉시 제외 (포함 조건보다 우선)
    if exclude_keywords and _keyword_match(announcement, exclude_keywords):
        logger.debug("제외 키워드 매칭: '%s'", announcement.get("공고명", ""))
        return False

    # 포함 필터가 모두 비어 있으면 전체 수집
    if not keywords and not categories:
        return True

    keyword_hit = _keyword_match(announcement, keywords)
    category_hit = _category_match(announcement, categories)

    if logic == "AND":
        # 키워드 필터가 없으면 AND 조건에서 키워드 쪽은 항상 True 처리
        kw_ok = keyword_hit if keywords else True
        cat_ok = category_hit if categories else True
        return kw_ok and cat_ok
    else:  # OR (기본값)
        return keyword_hit or category_hit


def _keyword_match(announcement: dict, keywords: list[str]) -> bool:
    """공고 제목 또는 내용요약에 키워드가 하나라도 포함되면 True."""
    if not keywords:
        return False
    search_text = " ".join([
        announcement.get("공고명", ""),
        announcement.get("내용요약", ""),
        announcement.get("발주기관", ""),
    ]).lower()
    for kw in keywords:
        if kw.lower() in search_text:
            logger.debug("키워드 매칭: '%s' → '%s'", kw, announcement.get("공고명", ""))
            return True
    return False


def _category_match(announcement: dict, categories: list[str]) -> bool:
    """공고의 카테고리 코드가 설정된 목록에 포함되면 True."""
    if not categories:
        return False
    ann_category = str(announcement.get("카테고리코드", "")).strip()
    return ann_category in categories


# ─────────────────────────────────────────────────────────────────────────────
# 나라장터 전용 정제 필터 (v1.0)
# ─────────────────────────────────────────────────────────────────────────────

def refine_g2b(announcement: dict, g2b_cfg: dict) -> bool:
    """
    나라장터 공고에 대한 로컬 정제 필터.
    g2b.py에서 _단계/_계약방법/_낙찰방법/_예산금액 필드를 부착한 공고에 적용한다.

    Args:
        announcement : 표준 공고 딕셔너리 (필터 전용 '_단계' 등 포함).
        g2b_cfg      : config["sites"]["g2b"] 딕셔너리.

    Returns:
        True면 최종 수집 대상, False면 제외.

    적용 순서 (모두 AND 결합):
        1. exclude_keywords — 공고명/품명에 포함 시 제외
        2. contract_methods — 입찰공고만, 비면 통과 (exact match)
        3. award_methods    — 입찰공고만, 비면 통과, 부분일치
        4. budget_min/max   — null이면 해당 방향 무제한
    """
    title   = announcement.get("공고명", "")
    stage   = announcement.get("_단계", "")         # "입찰공고" | "사전규격"
    contract_method = announcement.get("_계약방법", "")
    award_method    = announcement.get("_낙찰방법", "")
    budget_int      = announcement.get("_예산금액", None)  # 정수 또는 None

    # 1. 제외 키워드 (공고명 포함 시 즉시 제외)
    exclude_keywords: list[str] = g2b_cfg.get("exclude_keywords", [])
    if exclude_keywords:
        title_lower = title.lower()
        for kw in exclude_keywords:
            if kw.lower() in title_lower:
                logger.debug("[G2B 필터] 제외 키워드 '%s' 매칭: '%s'", kw, title)
                return False

    # 2. 계약방법 (입찰공고만 적용)
    contract_methods: list[str] = g2b_cfg.get("contract_methods", [])
    if stage == "입찰공고" and contract_methods:
        if contract_method not in contract_methods:
            logger.debug(
                "[G2B 필터] 계약방법 불일치 '%s' (허용: %s): '%s'",
                contract_method, contract_methods, title,
            )
            return False

    # 3. 낙찰방법 (입찰공고만 적용, 부분일치)
    # 실제 API 값이 "협상에의한계약-협상에 의한 계약" 형태의 복합 문자열이므로
    # award_methods의 각 값이 _낙찰방법 안에 부분문자열로 있으면 매칭
    award_methods: list[str] = g2b_cfg.get("award_methods", [])
    if stage == "입찰공고" and award_methods:
        matched = any(am in award_method for am in award_methods)
        if not matched:
            logger.debug(
                "[G2B 필터] 낙찰방법 불일치 '%s' (허용: %s): '%s'",
                award_method, award_methods, title,
            )
            return False

    # 4. 예산 범위
    budget_min = g2b_cfg.get("budget_min", None)
    budget_max = g2b_cfg.get("budget_max", None)
    if budget_int is not None:
        if budget_min is not None and budget_int < budget_min:
            logger.debug(
                "[G2B 필터] 예산 %d < min %d: '%s'",
                budget_int, budget_min, title,
            )
            return False
        if budget_max is not None and budget_int > budget_max:
            logger.debug(
                "[G2B 필터] 예산 %d > max %d: '%s'",
                budget_int, budget_max, title,
            )
            return False

    return True
