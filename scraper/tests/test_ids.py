"""
단위 테스트: ids.derive_stable_id() 3패턴 처리 검증

목적:
  - nttNo, bidPbancNo, bfSpecRegNo 세 패턴 모두 올바른 stable_id 생성
  - 형식: "{site}-{값}"
  - 매칭 실패 시 빈 문자열 반환
  - 빈 링크 입력 시 빈 문자열 반환
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.ids import derive_stable_id


class TestNipaPattern:
    """패턴 1: nttNo 파라미터 (NIPA 사이트)"""

    def test_nttno_query_param(self):
        url = "https://www.nipa.kr/biz/notice?nttNo=16756"
        result = derive_stable_id("NIPA", url)
        assert result == "NIPA-16756"

    def test_nttno_with_other_params_before(self):
        url = "https://www.nipa.kr/biz/notice?page=2&nttNo=99999"
        result = derive_stable_id("NIPA", url)
        assert result == "NIPA-99999"

    def test_nttno_with_other_params_after(self):
        url = "https://www.nipa.kr/biz/notice?nttNo=12345&category=ai"
        result = derive_stable_id("NIPA", url)
        assert result == "NIPA-12345"


class TestG2bBidNoticePattern:
    """패턴 2: bidPbancNo 파라미터 (나라장터 입찰공고)"""

    def test_bid_notice_link(self):
        url = "https://www.g2b.go.kr/link/PNPE027_01/single/?bidPbancNo=R26BK01554166&bidPbancOrd=000"
        result = derive_stable_id("나라장터", url)
        assert result == "나라장터-R26BK01554166"

    def test_bid_notice_without_trailing_param(self):
        url = "https://www.g2b.go.kr/test?bidPbancNo=R26BK01550144"
        result = derive_stable_id("나라장터", url)
        assert result == "나라장터-R26BK01550144"

    def test_bid_notice_stops_at_ampersand(self):
        """bidPbancNo 값이 & 앞에서 잘려야 한다."""
        url = "https://www.g2b.go.kr/test?bidPbancNo=R26BK01234567&extra=foo"
        result = derive_stable_id("나라장터", url)
        assert result == "나라장터-R26BK01234567"


class TestG2bPreStandardPattern:
    """패턴 3: bfSpecRegNo 파라미터 (나라장터 사전규격)"""

    def test_pre_standard_query_param(self):
        # 실제 URL 구성: PRE_STANDARD_DETAIL_BASE.format(bfSpecRgstNo=...)
        url = "https://www.g2b.go.kr/pn/pnz/pnza/pubPrcureThng/detail.do?bfSpecRegNo=R26BD00232564"
        result = derive_stable_id("나라장터", url)
        assert result == "나라장터-R26BD00232564"

    def test_pre_standard_case_insensitive_n(self):
        """bfSpecRegNo(대문자N) 변형도 처리해야 한다."""
        url = "https://www.g2b.go.kr/test?bfSpecRegNo=R26BD00000001"
        result = derive_stable_id("나라장터", url)
        assert result == "나라장터-R26BD00000001"


class TestPatternPriority:
    """여러 파라미터가 동시에 있을 때 우선순위: nttNo > bidPbancNo > bfSpecRegNo"""

    def test_nttno_takes_priority_over_bid(self):
        url = "https://example.com?nttNo=111&bidPbancNo=222"
        result = derive_stable_id("사이트", url)
        assert result == "사이트-111"

    def test_bidpbancno_takes_priority_over_bfspec(self):
        url = "https://example.com?bidPbancNo=AAA&bfSpecRegNo=BBB"
        result = derive_stable_id("사이트", url)
        assert result == "사이트-AAA"


class TestFailureCases:
    """매칭 실패 및 엣지 케이스"""

    def test_empty_link_returns_empty(self):
        result = derive_stable_id("나라장터", "")
        assert result == ""

    def test_no_matching_param_returns_empty(self):
        url = "https://www.example.com/some/random/path?foo=bar"
        result = derive_stable_id("사이트", url)
        assert result == ""

    def test_source_site_prefix_is_preserved(self):
        url = "https://example.com?nttNo=999"
        result = derive_stable_id("ETRI", url)
        assert result.startswith("ETRI-")

    def test_none_like_empty_string(self):
        result = derive_stable_id("나라장터", "")
        assert result == ""
