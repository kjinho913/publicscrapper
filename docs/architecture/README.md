# 시스템 아키텍처 개요

나라장터(G2B) 공고를 자동 수집·필터링·저장하고, 관심 공고를 선별 분석하는 파이프라인.
각 단계가 독립적으로 교체·재실행 가능하도록 설계됐다.

> 기술 결정의 배경과 이유는 이 문서가 아닌 **`docs/architecture/ADR-001~004`** 에 있다.
> 이 문서는 "현재 시스템 한눈에 보기" 개요 역할로 한정한다. (`docs/architecture/README.md`)

---

## 전체 구조 (디렉토리)

```
webscrap/
├── analysis/               ← rfp-analyzer 분석 결과 저장소 ({stable_id}/result.html 등)
├── dashboard/              ← Flask 로컬 웹앱 (app.py, datasource.py, index.html)
├── docs/                   ← 프로젝트 문서 (세션로그·워크플로우·아키텍처)
│   ├── architecture/       ← 구조 명세 (이 문서 포함)
│   │   ├── README.md       ← 이 파일 (시스템 구조 개요)
│   │   ├── ADR-001~004.md
│   ├── sessions/
│   └── refference/         ← 개발 참고자료 (정본 아님 — README.md 참조)
├── scripts/                ← 실행 진입점 (run_dashboard.bat 등)
├── scraper/                ← 수집 파이프라인 코어
│   ├── config.yaml         ← 모든 설정의 단일 진실 공급원
│   ├── main.py             ← 수집 진입점
│   ├── core/               ← 수집 모듈
│   │   ├── scrapers/       ← 사이트별 스크래퍼 (g2b.py, nipa.py, mss.py, nia.py, etri.py)
│   │   ├── filters.py      ← 키워드·정제 필터
│   │   ├── runner.py       ← 사이트별 실행 조율
│   │   ├── json_store.py   ← JSON 정본 저장소 I/O
│   │   ├── ids.py          ← stable_id 파생 (공용 모듈)
│   │   ├── downloader.py   ← 첨부파일 다운로드
│   │   ├── converter.py    ← HWP/HWPX→PDF 변환 (win32com)
│   │   ├── excel_writer.py ← 보존됨 (Excel export backlog용, 현재 미사용)
│   │   └── playwright_helper.py
│   ├── output/
│   │   ├── announcements.json  ← 정본 저장소 (수집 기록 단일 진실 공급원)
│   │   └── attachments/        ← 선별 다운로드된 첨부파일
│   └── logs/
└── tasks/
```

---

## 수집 파이프라인

```
[나라장터 API (PPSSrch)]
    │
    ▼
① 목록 수집 (scraper/core/scrapers/g2b.py)
    │  입찰공고 / 사전규격 2단계 순회
    │  키워드별 서버 검색 → 결과 합집합 + 중복 제거
    │
    ▼
② 로컬 정제 (scraper/core/filters.py — refine_g2b)
    │  제외 키워드 / 계약방법 / 낙찰방법 / 예산 범위 필터
    │
    ▼
③ JSON 정본 저장 (scraper/core/json_store.py)
    │  upsert: 변동 필드 갱신, 보존 필드(분석상태·판단상태) 유지
    │  저장소: scraper/output/announcements.json
    │
    ▼
[사용자 — 대시보드에서 선별]
    │
    ▼
④ 선별 다운로드 + 변환 (dashboard/app.py 버튼 트리거)
    │  첨부파일 다운로드 → HWP/HWPX → PDF 변환 (win32com 한글)
    │  저장: scraper/output/attachments/{stable_id}/
    │
    ▼
⑤ rfp-analyzer 분석 (Claude Code 에이전트 수동 트리거)
    │  PDF 경로 → 9개 섹션 HTML 리포트 생성
    │  저장: analysis/{stable_id}/result.html
    │
    ▼
[대시보드 탭2] 리포트 자동 표시 (result.html iframe 표시 + 다운로드)
```

> 수집 시 자동 다운로드는 폐지됐다(ADR-004). 첨부 URL은 JSON 레코드에 저장하고, 사용자가 대시보드에서 필요한 공고만 선별 다운로드한다.

---

## 스크래퍼

`BaseScraper` (`scraper/core/scrapers/base.py`)는 requests session, retry/backoff (500·502·503·504), 랜덤 딜레이(1–3초), 인코딩 자동감지를 제공한다.
각 사이트 스크래퍼는 `BaseScraper`를 상속해 `fetch_list()`와 `fetch_detail()`만 구현한다.

| 스크래퍼 | 방식 | 현재 활성화 | 주요 특이사항 |
|---|---|---|---|
| `g2b.py` | 나라장터 공공데이터포털 API (XML, PPSSrch) | `true` | 입찰공고/사전규격 2단계, 키워드별 서버 검색, stable_id 기록 |
| `nipa.py` | HTML 파싱 | `false` | `curPage` 파라미터, `nttDetail?nttNo={ID}` 상세 URL |
| `mss.py` | HTML 파싱 | `false` | `onclick="doBbsFView('310','bcIdx',...)"` 에서 bcIdx 추출 |
| `nia.py` | HTML 파싱 | `false` | `onclick="doBbsFView('78336','bcIdx',...)"` 에서 bcIdx 추출 |
| `etri.py` | HTML 파싱 (POST) | `false` | POST 방식 페이지네이션 |

활성화 여부는 `scraper/config.yaml`의 `sources` 섹션에서 설정.

새 사이트 추가 절차:
1. `scraper/core/scrapers/` 에 파일 생성 (`BaseScraper` 상속)
2. `scraper/core/scrapers/__init__.py` 에 클래스 export
3. `scraper/main.py`의 `_ALL_SITES` 목록에 추가
4. `scraper/config.yaml`의 `sources`, `sites` 섹션에 추가

---

## JSON 정본 저장소

**파일**: `scraper/output/announcements.json`
**구조**: `stable_id`를 키로 하는 dict

```
stable_id — URL 기반 고유키
  나라장터 입찰공고: bidPbancNo
  나라장터 사전규격: bfSpecRegNo
  NIPA: nttNo
```

**레코드 주요 필드**: stable_id, 공고번호, 공고명, 발주기관, 출처사이트, 단계(입찰공고|사전규격), 공고일, 마감일시, 예산금액, 내용요약, 공고링크, 첨부파일수, 첨부파일경로(URL), 최초수집일시, 최종수집일시, analyzed(bool), 분석경로, 판단상태(미검토|관심|참여검토|제외)

**upsert 규칙**: 재수집 시 변동 필드(공고명/마감일/예산/내용/단계/최종수집일시)는 갱신하고, 보존 필드(최초수집일시/analyzed/분석경로/판단상태/첨부파일)는 유지한다.

---

## 로컬 대시보드 (Flask 웹앱)

**실행**: `scripts/run_dashboard.bat` → `http://127.0.0.1:5050`

| 컴포넌트 | 역할 |
|---|---|
| `dashboard/app.py` | Flask 서버, API 엔드포인트 |
| `dashboard/datasource.py` | announcements.json + analysis/ 합산 → 목록 데이터 |
| `dashboard/index.html` | 2탭 SPA (탭1: 공고 목록/다운로드, 탭2: 분석 리포트) |

**주요 API**:

| 엔드포인트 | 동작 |
|---|---|
| `GET /api/announcements` | 공고 목록 + 상태 반환 |
| `POST /api/download/<stable_id>` | 백그라운드 다운로드 + HWP→PDF 변환 |
| `GET /api/status/<stable_id>` | 다운로드 진행 상태 |
| `GET /api/report/<stable_id>` | result.html 또는 result.md→HTML 변환 반환 |
| `GET /api/report/<stable_id>/download` | result.html 파일 다운로드 |

**분석 완료 판정**: `analysis/{stable_id}/result.html` (신형) 또는 `result.md` (구형 하위호환) 존재 여부로 serve-time 파생.

---

## 필터 (`scraper/core/filters.py`)

- **`matches()`**: NIPA·MSS·NIA·ETRI 등 나라장터 외 사이트에 적용되는 공통 키워드 필터.
  - 검색 대상: `공고명 + 내용요약 + 발주기관` (소문자 비교)
  - `keywords` (OR/AND): 하나라도 포함되면 통과
  - `exclude_keywords`: 하나라도 포함되면 제외 (keywords보다 우선)
- **`refine_g2b()`**: 나라장터 전용 로컬 정제 필터.
  - 제외 키워드 / 계약방법 허용 목록 / 낙찰방법 허용 목록 / 예산 범위

---

## 설정 (`scraper/config.yaml`)

모든 스크래퍼 설정의 단일 진실 공급원. 코드 수정 없이 URL·키워드·필터를 조정한다.

```yaml
sources:              # 사이트별 활성화 여부
  g2b: true
  nipa: false
  ...

filters:              # 나라장터 외 사이트 공통 키워드 필터
  keywords: [...]
  exclude_keywords: []
  match_logic: "OR"

sites:
  g2b:
    stages:
      bid_notice: true      # 입찰공고
      pre_standard: true    # 사전규격
    date_range_days: 3      # 수집 기간 (오늘 기준 N일 전)
    search_keywords: [...]  # 서버 검색 키워드
    exclude_keywords: [...]
    contract_methods: []
    award_methods: [...]
    budget_min: null
    budget_max: null

api_keys:
  g2b_api_key: ""     # 공공데이터포털 발급 키 (.env의 G2B_API_KEY 권장)
```

---

## 출력 산출물

| 경로 | 내용 |
|---|---|
| `scraper/output/announcements.json` | 수집 정본 저장소 (stable_id 키) |
| `scraper/output/attachments/{stable_id}/` | 선별 다운로드된 첨부파일 + 변환 PDF |
| `analysis/{stable_id}/result.html` | rfp-analyzer 분석 리포트 (신형) |
| `analysis/{stable_id}/result.md` | rfp-analyzer 분석 리포트 (구형, 하위호환) |
| `analysis/{stable_id}/meta.json` | 분석 메타데이터 |
| `scraper/logs/scraper_YYYY-MM-DD.log` | 수집 실행 로그 |

---

## HTML 구조 변경 대응 (나라장터 외 사이트)

사이트 리뉴얼로 수집이 안 되면:
1. `python main.py --debug-{site}` 로 원본 HTML 출력
2. 각 스크래퍼 파일 상단의 `SEL_*` 상수 수정
3. 필요 시 `config.yaml`의 `sites.{site}.list_url` 수정
