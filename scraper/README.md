# 공공기관 사업공고 자동 수집기

공공기관 5개 사이트의 사업공고를 자동 수집하여 Excel로 저장하고 첨부파일을 다운로드합니다.

## 대상 사이트

| 기관명 | URL |
|---|---|
| 정보통신산업진흥원 (NIPA) | https://www.nipa.kr |
| 중소벤처기업부 (MSS) | https://www.mss.go.kr |
| 나라장터 (G2B) | https://www.g2b.go.kr |
| 한국지능정보사회진흥원 (NIA) | https://www.nia.or.kr |
| 한국전자통신연구원 (ETRI) | https://ebid.etri.re.kr |

---

## 1. 설치

```bash
# Python 3.10 이상 필요
pip install -r requirements.txt
```

---

## 2. 나라장터 API 키 발급 및 설정

1. [공공데이터포털](https://www.data.go.kr) 회원가입 후 로그인
2. 검색창에 **"입찰공고정보"** 검색
3. **"나라장터 입찰공고정보"** 서비스 → **[활용신청]** 클릭
4. 신청 승인 후 **마이페이지 → 개발계정** 에서 API 키(Encoding) 확인
5. `config.yaml` 편집:

```yaml
api_keys:
  g2b_api_key: "발급받은키를여기에입력"
```

---

## 3. 실행

### 한 번 실행 (수동)
```bash
python main.py --once
```

### 자동 스케줄 (프로세스 유지 방식)
```bash
python main.py --schedule
```

### Windows 작업 스케줄러 등록 (권장)

작업 스케줄러를 통해 매일 자동 실행하는 것이 가장 안정적입니다.

1. **[시작]** → "작업 스케줄러" 검색 → 실행
2. 오른쪽 패널 **[작업 만들기]** 클릭
3. **일반 탭**: 이름 = `공고수집기`, "최고 수준의 권한으로 실행" 체크
4. **트리거 탭**: [새로 만들기] → 매일 → 시작 시간 `08:00`
5. **동작 탭**: [새로 만들기]
   - 프로그램/스크립트: `C:\Python312\python.exe` (Python 경로)
   - 인수 추가: `app/main.py --once`
   - 시작 위치: `D:\경로\scraper` (이 폴더의 절대 경로)
6. **확인** → 작업 저장

---

## 4. 설정 (`config.yaml`)

```yaml
sources:
  nipa: true    # 정보통신산업진흥원
  mss:  true    # 중소벤처기업부
  g2b:  true    # 나라장터 (API 키 필요)
  nia:  true    # 한국지능정보사회진흥원
  etri: true    # 한국전자통신연구원

filters:
  keywords:
    - "AI"
    - "데이터"
    - "용역"
  exclude_keywords: []   # 공고명/내용에 이 키워드가 있으면 제외 (포함 키워드보다 우선)
  categories: []         # 나라장터 업종코드 (비워두면 전체 수집)
  match_logic: "OR"      # OR | AND

attachments:
  enabled: true
  download_dir: "./output/attachments"
  max_file_size_mb: 50

output:
  directory: "./output"
  rolling_file: true     # true: 단일 파일 누적 | false: 날짜별 파일
  filename: "announcements.xlsx"
```

---

## 5. 출력 구조

```
scraper/
├── output/
│   ├── announcements.xlsx        ← 공고 목록 Excel
│   └── attachments/
│       ├── NIPA/
│       │   └── 20240001/
│       │       ├── 공고문.pdf
│       │       └── 제안요청서.hwp
│       ├── 나라장터/
│       └── ...
└── logs/
    └── scraper_2026-03-03.log    ← 실행 로그
```

**Excel 컬럼:** 공고번호, 공고명, 발주기관, 출처사이트, 공고일, 마감일시, 예산금액, 내용요약, 첨부파일수, 첨부파일경로, 공고링크, 수집일시

- 마감일이 7일 이내인 행은 **주황색** 강조
- 공고링크, 첨부파일경로는 클릭 가능한 하이퍼링크

실행 완료 시 사이트별 수집 통계를 로그에 출력합니다:

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

## 6. CSS 셀렉터 조정 (HTML 스크래퍼)

NIPA, MSS, NIA, ETRI는 HTML 스크래핑 방식입니다.
사이트 리뉴얼 등으로 목록을 찾지 못하면 셀렉터를 조정해야 합니다.

**디버그 명령어로 원본 HTML 확인:**
```bash
python app/main.py --debug-nipa
python app/main.py --debug-mss
python app/main.py --debug-nia
python app/main.py --debug-etri
```

출력된 HTML을 보고 각 스크래퍼 파일 상단의 `SEL_*` 상수를 수정하세요.

상세 페이지 첨부파일 셀렉터를 확인하려면:
```bash
python app/main.py --debug-detail nia <공고URL>
```

**NIPA 셀렉터 위치:** `scrapers/nipa.py` 상단 `SEL_ROWS`, `SEL_TITLE_LINK` 등
**MSS 셀렉터 위치:** `scrapers/mss.py` 상단
**NIA 셀렉터 위치:** `scrapers/nia.py` 상단
**ETRI 셀렉터 위치:** `scrapers/etri.py` 상단

---

## 7. 트러블슈팅

| 증상 | 원인 | 해결 |
|---|---|---|
| G2B 수집 0건 | API 키 미설정 | `config.yaml`에 `g2b_api_key` 입력 |
| 특정 사이트 수집 0건 | 셀렉터 불일치 | `--debug-{site}`로 HTML 확인 후 `SEL_*` 상수 수정 |
| 사이트 URL 변경 후 오류 | 게시판 ID 변경 | `config.yaml`의 `sites.{site}.list_url` 수정 |
| 첨부파일 다운로드 실패 | 로그인 필요 페이지 | 로그에서 URL 확인, 현재 버전 범위 외 |
| Excel 파일 열기 오류 | 파일 열린 상태에서 실행 | Excel 파일 닫은 후 재실행 |
