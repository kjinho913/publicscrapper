# ADR-002: 나라장터 v1.0 수집 파이프라인 (PPSSrch 전환)

- **Date:** 2026-06-02
- **Status:** Accepted

## Context

프로토타입에서 나라장터를 `getBidPblancListInfoServc`(날짜범위 전량조회)로 수집해 output이 폭증했다.
v1.0은 나라장터 단일 사이트에 집중하며, 검색어 기반 제한적 수집으로 전환한다.
API 검증 결과(2026-06-02 세션 기록 참조), 입찰공고/사전규격 모두 PPSSrch 오퍼레이션에서 검색어 서버 필터가 동작함을 확인했다.

## Decision

"전량 수집 → 로컬 필터" → **"서버 검색으로 소수 수집 → 로컬 정제 → 다운로드"** 로 전환.

### 결정 1: 단일 G2bScraper가 단계(stages) 내부 순회
- 입찰공고/사전규격을 별도 클래스로 나누지 않고 fetch_list 내부에서 분기
- 근거: _SCRAPER_MAP/runner/config 사이트 키 구조 변경 최소화

### 결정 2: 복수 키워드 = 키워드별 PPSSrch 호출 후 합집합 + 중복제거
- 검색어 파라미터는 한 번에 1개 → 키워드마다 호출
- (공고번호, 단계) 기준 중복 제거

### 결정 3: 로컬 정제 필터는 filters.py에 refine_g2b() 신설
- 기존 matches()는 다른 사이트가 쓰므로 보존
- "포함"은 서버(fetch_list), "정제(제외/계약방법/낙찰방법/예산)"는 refine_g2b로 책임 분리

## Consequences

- 얻는 것: output 폭증 해소, 단계 2종 지원, 키워드 OR 자연 지원, 타 사이트 코드 무손상
- 어려워지는 것: g2b 파서가 입찰공고/사전규격 2개 스키마 분기 필요, runner에 g2b 분기 1곳
- 되돌리기: 쉬움 (기존 matches()/사이트 구조 보존)

## 변경 대상 파일
- scraper/core/scrapers/g2b.py — PPSSrch 2종, 단계 순회, 키워드 다중호출+중복제거, 2스키마 파서, 필터전용 필드 부착
- scraper/core/filters.py — refine_g2b() 신설
- scraper/core/runner.py — g2b는 refine_g2b 사용 분기, 필터 설정을 sites.g2b에서 읽기
- scraper/config.yaml — sites.g2b 섹션 재구성 (planner 확정 스펙)

## 코딩 단계 검증 리스크
1. PPSSrch/사전규격의 첨부파일 URL 필드명 (기존 ntceSpecDocUrl1~10과 다를 수 있음)
2. 사전규격 공고링크/마감일 필드 (refNo, opninRgstClseDt 등 입찰공고와 키 상이)
3. 낙찰방법 부분일치 (복합 문자열 "협상에의한계약-..." 앞부분 분류명 매칭)

## 관련 문서
- 필터 스펙 및 API 검증: docs/sessions/2026-06-02.md
- 디렉토리 구조: docs/architecture/ADR-001-directory-restructure.md
