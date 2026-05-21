## Architecture

공공기관 5개 사이트의 사업공고를 자동 수집·필터링·저장하는 파이프라인.
각 단계가 독립적으로 동작하므로 특정 단계만 교체·재실행하기 쉽게 설계됐다.

---

### Pipeline (`app/main.py` orchestrates)

```
[각 사이트]
    │
    ▼
① 목록 수집 (fetch_list)
    │  스크래퍼가 목록 페이지를 최대 N페이지 순회
    │  → 공고번호, 제목, 발주기관, 공고일, 마감일, 링크 추출
    │
    ▼
② 상세 수집 (fetch_detail)
    │  각 공고 상세 페이지 방문
    │  → 내용요약, 예산금액, 첨부파일 URL 보완
    │  (G2B는 API에서 이미 상세 정보 포함)
    │
    ▼
③ 키워드 필터링 (app/filters.py)
    │  포함 키워드 OR/AND 검사 → 통과
    │  제외 키워드 검사 → 포함 시 제외 (포함 키워드보다 우선)
    │
    ▼
④ 첨부파일 다운로드 (app/downloader.py)
    │  허용 확장자·최대 크기 검사 후 스트리밍 다운로드
    │  저장 경로: output/attachments/{출처사이트}/{공고번호}/
    │
    ▼
⑤ Excel 저장 (app/excel_writer.py)
    │  (공고번호, 출처사이트) 기준 중복 제거 후 신규 행만 추가
    │  마감 7일 이내 행 → 주황 하이라이트
    │  공고링크·첨부경로 → 클릭 가능한 하이퍼링크
    │
    ▼
output/announcements.xlsx  (누적 갱신)
output/attachments/...     (첨부파일)
logs/scraper_YYYY-MM-DD.log
```

> 각 단계는 이전 단계의 출력(dict 리스트 또는 파일 경로)만 받아 동작한다.
> 단계 간 결합을 최소화해 특정 단계만 교체하거나 재실행하기 쉽게 설계한다.

---

### Scrapers

`BaseScraper` (`scrapers/base.py`)는 requests session, retry/backoff (500·502·503·504), 랜덤 딜레이(1–3초), EUC-KR/UTF-8 인코딩 자동감지를 제공한다.
각 사이트 스크래퍼는 `BaseScraper`를 상속해 `fetch_list()`와 `fetch_detail()`만 구현한다.

| 스크래퍼 | 방식 | 주요 특이사항 |
|---|---|---|
| `nipa.py` | HTML 파싱 | `curPage` 파라미터, `nttDetail?nttNo={ID}` 상세 URL |
| `mss.py` | HTML 파싱 | `onclick="doBbsFView('310','bcIdx',...)"` 에서 bcIdx 추출 → 상세 URL 조합 |
| `g2b.py` | 공공데이터포털 Open API (XML) | `inqryDiv=1`, 최근 7일, 최대 10페이지(1,000건); 첨부파일 URL은 상세 HTML 파싱 |
| `nia.py` | HTML 파싱 | `onclick="doBbsFView('78336','bcIdx',...)"` 에서 bcIdx 추출; `span.src`에서 날짜 추출 |
| `etri.py` | HTML 파싱 (POST) | POST 방식 페이지네이션; 상세는 팝업 구조 |

새 사이트 추가 절차:
1. `scrapers/` 에 파일 생성 (`BaseScraper` 상속, `fetch_list()` + `fetch_detail()` 구현)
2. `scrapers/__init__.py` 에 클래스 export
3. `app/main.py`의 `_SCRAPER_MAP` 에 등록
4. `app/config.yaml`의 `sources`, `sites` 섹션에 추가

---

### Filter (`app/filters.py`)

- 검색 대상: `공고명 + 내용요약 + 발주기관` (소문자 변환 후 비교)
- `keywords` (OR/AND): 하나라도 포함되면 통과
- `exclude_keywords`: 하나라도 포함되면 제외 (keywords보다 우선)
- 사이트별 필터 오버라이드: `config.yaml`의 `sites.{site}.filters`가 전역 설정에 병합됨
  - 예: G2B 전용 `exclude_keywords: ["물품구매", "시설공사", ...]`

---

### Downloader (`app/downloader.py`)

- 허용 확장자(`attachments.allowed_extensions`)와 최대 파일 크기 검사 후 다운로드
- 저장 경로: `output/attachments/{출처사이트}/{공고번호}/`
- 이미 존재하는 파일은 스킵
- Content-Disposition 헤더에서 한글 파일명 추출 (RFC 5987 + EUC-KR 처리)
- 스트리밍 다운로드로 대용량 파일 메모리 효율 확보

---

### Configuration (`app/config.yaml`)

```yaml
sources:              # 사이트별 활성화 여부
  nipa: true
  ...

filters:
  keywords: ["AI", "데이터", ...]       # 포함 키워드
  exclude_keywords: []                  # 제외 키워드 (포함 키워드보다 우선)
  match_logic: "OR"                     # OR | AND

attachments:
  enabled: true
  allowed_extensions: [".pdf", ".hwp", ...]
  max_file_size_mb: 50

sites:                # URL/ID 변경 시 이 섹션만 수정
  nipa:
    list_url: "..."
    page_param: "curPage"
    max_pages: 5
  g2b:
    api_base: "..."
    max_pages: 10
    filters:          # 사이트 전용 제외 키워드 (전역 설정에 병합)
      exclude_keywords: ["물품구매", "시설공사", ...]
  ...

api_keys:
  g2b_api_key: ""     # 공공데이터포털 발급 키
```

설정을 코드 밖으로 분리한 이유: 사이트 리뉴얼 시 URL·게시판 ID를 코드 수정 없이 조정하고, API 키를 `.gitignore`된 파일에 격리하기 위함.

---

### Output

| 경로 | 내용 |
|---|---|
| `output/announcements.xlsx` | 전체 공고 누적 (중복 제거) |
| `output/attachments/{사이트}/{공고번호}/` | 다운로드된 첨부파일 |
| `logs/scraper_YYYY-MM-DD.log` | 실행 로그 + 사이트별 수집 통계 표 |

실행 완료 시 로그에 출력되는 통계 표 예시:

```
------------------------------------------------------------
사이트             수집    필터    첨부
------------------------------------------------------------
NIPA               50건    12건     2개
중소벤처기업부     10건     4건     1개
나라장터            0건     0건     0개  [오류]
NIA                 5건     1건     0개
ETRI                3건     0건     0개
------------------------------------------------------------
합계               68건    17건     3개  (Excel 신규: 15건)
------------------------------------------------------------
```

---

### HTML 구조 변경 대응

사이트 리뉴얼로 수집이 안 되면:

1. `python app/main.py --debug-{site}` 로 원본 HTML 출력
2. 각 스크래퍼 파일 상단의 `SEL_*` 상수 수정
3. 필요 시 `config.yaml`의 `sites.{site}.list_url` 수정

```python
# 예: scrapers/nia.py 상단 셀렉터
SEL_ROWS       = "ul li"
SEL_TITLE_LINK = "a[onclick*='doBbsFView']"
SEL_FILES      = "a[href*='/common/board/Download.do']"
```
