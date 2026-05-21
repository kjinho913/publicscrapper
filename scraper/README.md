# 공공기관 사업공고 자동 수집기

공공기관 5개 사이트의 사업공고를 자동으로 수집하여 Excel로 저장하고 첨부파일을 다운로드합니다.
키워드 필터링으로 원하는 공고만 추출하고, 마감 임박 공고는 자동으로 강조 표시합니다.

## 대상 사이트

| 기관 | URL | 수집 방식 |
|---|---|---|
| 정보통신산업진흥원 (NIPA) | https://www.nipa.kr | HTML 스크래핑 |
| 중소벤처기업부 (MSS) | https://www.mss.go.kr | HTML 스크래핑 |
| 나라장터 (G2B) | https://www.g2b.go.kr | 공공데이터포털 Open API |
| 한국지능정보사회진흥원 (NIA) | https://www.nia.or.kr | HTML 스크래핑 |
| 한국전자통신연구원 (ETRI) | https://ebid.etri.re.kr | HTML 스크래핑 (POST) |

---

## 주요 기능

- **자동 수집**: 목록 페이지 페이지네이션 → 상세 페이지 순차 방문
- **키워드 필터링**: 포함/제외 키워드, OR/AND 로직, 사이트별 오버라이드
- **첨부파일 다운로드**: 허용 확장자·최대 크기 검사, 중복 스킵, 한글 파일명 지원
- **Excel 저장**: 중복 제거 누적, 마감 7일 이내 주황 강조, 링크 하이퍼링크화
- **병렬 실행**: 복수 사이트 선택 시 ProcessPoolExecutor 병렬 처리
- **스케줄 모드**: 매일 지정 시각 자동 실행

---

## 설치

Python 3.10 이상이 필요합니다.

```bash
# 가상환경 생성 (선택)
python -m venv .venv
.venv\Scripts\activate      # Windows
source .venv/bin/activate   # macOS/Linux

# 의존성 설치
pip install -r requirements.txt
```

---

## 초기 설정

### 1. 환경변수 파일 생성

`.env.example`을 복사해 `.env`를 만들고 API 키를 입력합니다.

```bash
copy .env.example .env      # Windows
cp .env.example .env        # macOS/Linux
```

`.env` 파일:

```
G2B_API_KEY=발급받은키를여기에입력
```

> **`.env`는 절대 Git에 커밋하지 마세요.** `.gitignore`에 이미 포함되어 있습니다.

### 2. 나라장터 API 키 발급

G2B(나라장터)는 공공데이터포털 API 키가 필요합니다.

1. [공공데이터포털](https://www.data.go.kr) 회원가입 후 로그인
2. **"나라장터 입찰공고정보"** 검색 → [활용신청]
3. 승인 후 **마이페이지 → 개발계정**에서 Encoding 키 확인
4. 위 키를 `.env`의 `G2B_API_KEY`에 입력

G2B를 사용하지 않는다면 `config.yaml`에서 `sources.g2b: false`로 설정합니다.

### 3. 수집 대상 및 필터 설정

`config.yaml`을 편집합니다.

```yaml
sources:
  nipa: true    # 수집할 사이트만 true
  mss:  true
  g2b:  true
  nia:  true
  etri: true

filters:
  keywords:
    - "AI"
    - "인공지능"
    - "데이터"
    - "용역"
  exclude_keywords: []   # 이 단어가 공고명에 있으면 제외
  match_logic: "OR"      # OR | AND
```

---

## 실행 방법

### 사이트별 직접 실행

```bash
python main.py --nipa               # NIPA 단독
python main.py --nipa --g2b --nia   # 복수 선택 → 병렬 실행
python main.py --all                # 전체 사이트 병렬 실행
```

### config.yaml sources 기반 실행

```bash
python main.py --once               # 한 번 실행 후 종료
python main.py --schedule           # config.yaml의 schedule.time에 맞춰 매일 반복
```

### 디버그 (셀렉터 확인용)

```bash
python main.py --debug-nipa         # NIPA 목록 HTML 출력
python main.py --debug-mss          # MSS 목록 HTML 출력
python main.py --debug-nia          # NIA 목록 HTML 출력
python main.py --debug-etri         # ETRI 목록 HTML 출력

python main.py --debug-detail nipa <공고URL>   # 특정 공고 상세 HTML 출력
```

### 설정 파일 경로 지정

```bash
python main.py --once --config /path/to/config.yaml
```

---

## 출력 구조

```
output/
├── announcements.xlsx          ← 전체 공고 누적 Excel
└── attachments/
    ├── NIPA/
    │   └── 공고번호/
    │       ├── 공고문.pdf
    │       └── 제안요청서.hwp
    ├── 나라장터/
    ├── NIA/
    └── ...

logs/
└── scraper_2026-05-21.log      ← 실행 로그
```

**Excel 컬럼:** 공고번호 · 공고명 · 발주기관 · 출처사이트 · 공고일 · 마감일시 · 예산금액 · 내용요약 · 첨부파일수 · 첨부파일경로 · 공고링크 · 수집일시

- 마감일이 7일 이내인 행은 **주황색** 강조
- 공고링크, 첨부파일경로는 클릭 가능한 하이퍼링크
- (공고번호, 출처사이트) 조합 기준 중복 자동 제거

실행 완료 시 로그에 출력되는 통계:

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

## Windows 작업 스케줄러 등록

`--schedule` 대신 OS 스케줄러를 쓰는 방식이 더 안정적입니다.

1. **시작** → "작업 스케줄러" 실행
2. **[작업 만들기]** 클릭
3. **일반 탭**: 이름 = `공고수집기` / "최고 수준의 권한으로 실행" 체크
4. **트리거 탭**: 매일 → 시작 시간 `08:00`
5. **동작 탭**:
   - 프로그램: `D:\경로\scraper\.venv\Scripts\python.exe`
   - 인수: `main.py --once`
   - 시작 위치: `D:\경로\scraper`

---

## 프로젝트 구조

```
scraper/
├── main.py               ← 단일 CLI 진입점
├── config.yaml           ← 수집 설정 (사이트, 필터, 스케줄)
├── .env                  ← API 키 (Git 제외)
├── .env.example          ← 키 형식 안내 템플릿
├── requirements.txt
├── core/
│   ├── runner.py         ← 단일 사이트 파이프라인 (수집→필터→다운로드)
│   ├── scheduler.py      ← 순차/스케줄 실행, 디버그 헬퍼
│   ├── filters.py        ← 키워드·카테고리 필터
│   ├── downloader.py     ← 첨부파일 다운로드
│   ├── excel_writer.py   ← Excel 저장·포맷
│   └── scrapers/
│       ├── base.py       ← BaseScraper (세션, 재시도, 딜레이)
│       ├── nipa.py
│       ├── mss.py
│       ├── g2b.py
│       ├── nia.py
│       └── etri.py
├── logs/
├── output/
└── docs/
```

---

## 설정 레퍼런스 (`config.yaml`)

| 항목 | 설명 | 기본값 |
|---|---|---|
| `sources.{site}` | 사이트별 수집 활성화 | `true` |
| `filters.keywords` | 포함 키워드 목록 | - |
| `filters.exclude_keywords` | 제외 키워드 목록 | `[]` |
| `filters.match_logic` | `OR` / `AND` | `OR` |
| `attachments.enabled` | 첨부파일 다운로드 여부 | `true` |
| `attachments.max_file_size_mb` | 최대 파일 크기 | `50` |
| `output.rolling_file` | `true`: 단일 누적 파일 / `false`: 날짜별 파일 | `true` |
| `schedule.time` | 스케줄 실행 시각 (HH:MM) | `08:00` |
| `sites.{site}.max_pages` | 최대 수집 페이지 수 | `5` |
| `sites.{site}.list_url` | 게시판 URL (리뉴얼 시 여기만 수정) | - |
| `sites.g2b.date_range_days` | G2B 수집 기간 (오늘 기준 N일 전) | `7` |

---

## 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| G2B 수집 0건 | API 키 미설정 | `.env`에 `G2B_API_KEY` 입력 |
| 특정 사이트 수집 0건 | 셀렉터 불일치 | `--debug-{site}`로 HTML 확인 후 `core/scrapers/{site}.py` 상단 `SEL_*` 수정 |
| 사이트 URL 변경 후 오류 | 게시판 ID 변경 | `config.yaml`의 `sites.{site}.list_url` 수정 |
| 첨부파일 다운로드 실패 | 로그인 필요 페이지 | 현재 버전 대응 범위 외 |
| Excel 저장 오류 | 파일이 열린 상태 | Excel 파일 닫은 후 재실행 |

### 사이트 HTML 구조 변경 대응

사이트 리뉴얼로 수집이 안 되면:

1. 디버그 명령으로 실제 HTML을 확인합니다.
   ```bash
   python main.py --debug-nipa
   ```
2. `core/scrapers/{site}.py` 상단의 `SEL_*` 상수를 수정합니다.
   ```python
   # 예: core/scrapers/nia.py
   SEL_ROWS       = "ul li"
   SEL_TITLE_LINK = "a[onclick*='doBbsFView']"
   ```
3. 게시판 URL이 바뀌었다면 `config.yaml`의 `sites.{site}.list_url`을 수정합니다.

### 새 사이트 추가

1. `core/scrapers/{site}.py` 생성 (`BaseScraper` 상속, `fetch_list()` + `fetch_detail()` 구현)
2. `core/scrapers/__init__.py`에 클래스 export 추가
3. `core/scheduler.py`와 `core/runner.py`의 `_SCRAPER_MAP`에 등록
4. `main.py`의 `_ALL_SITES`에 사이트 키 추가
5. `config.yaml`의 `sources`, `sites` 섹션에 항목 추가
