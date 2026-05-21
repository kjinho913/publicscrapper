"""
키워드 + 카테고리 필터링 모듈.
config.yaml의 filters 섹션을 기반으로 공고의 포함 여부를 판별한다.
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
