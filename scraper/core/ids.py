"""
ids.py — stable_id 공용 파생 함수.

공고 링크 URL에서 재현 가능한 식별자(stable_id)를 추출한다.
저장소 키, 분석 폴더 이름, 중복 판정에 공통으로 사용된다.

지원 패턴:
  1. NIPA — nttNo 파라미터
  2. 나라장터 입찰공고 — bidPbancNo 파라미터
  3. 나라장터 사전규격 — bfSpecRegNo 파라미터 (URL 구성 시 사용)

형식: "{source_site}-{추출값}"
  예) "나라장터-R26BK01550144"
      "나라장터-R26BD00232564"
      "NIPA-16756"

매칭 실패 시 빈 문자열 반환.
"""

import re


def derive_stable_id(source_site: str, link: str) -> str:
    """
    공고 링크 URL에서 stable_id를 파생한다.

    Args:
        source_site: 출처사이트 이름 (예: "나라장터", "NIPA")
        link: 공고 상세 링크 URL

    Returns:
        "{source_site}-{추출값}" 형식의 문자열.
        추출 실패 시 빈 문자열.
    """
    if not link:
        return ""

    # 패턴 1: NIPA — nttNo 파라미터
    m = re.search(r"[?&]nttNo=(\d+)", link)
    if m:
        return f"{source_site}-{m.group(1)}"

    # 패턴 2: 나라장터 입찰공고 — bidPbancNo 파라미터
    m = re.search(r"[?&]bidPbancNo=([^&]+)", link)
    if m:
        return f"{source_site}-{m.group(1)}"

    # 패턴 3: 나라장터 사전규격 — bfSpecRegNo 파라미터 (URL path 또는 query)
    m = re.search(r"[?&/]bfSpecReg[Nn]o=([^&?/]+)", link)
    if m:
        return f"{source_site}-{m.group(1)}"

    return ""
