# ADR-004: 나라장터 v1.0 로컬 웹앱 전환 (버튼 다운로드·win32 HWP변환·분석 연결)

- **Date:** 2026-06-02
- **Status:** Accepted

## Context
관심 공고만 선별 다운로드·분석하려는 요구를 대시보드 버튼으로 통합. 정적 HTML로는 버튼이 백엔드 작업을 못 돌려 로컬 웹앱 전환 필요. 유료 API 미도입(분석은 구독 Claude Code 경유).

## Decision
- **대시보드를 Flask 로컬 웹앱으로 전환** — 정적 HTML+generate.py 폐기, 서버 실시간 조회(announcements.json + analysis/ 병합)
- **수집 시 첨부 자동 다운로드 폐지**, 첨부 URL을 announcements.json 레코드에 저장
- **버튼 클릭 → 백그라운드 다운로드 + HWP/HWPX→PDF 변환 → 판단상태=분석대기**
- **HWP→PDF 변환 = win32com 한컴 한글 COM 자동화** (LibreOffice 대신 오너가 win32 선택 — 변환 충실도 우선). 전제: PC에 한글 설치
- **분석완료 판정 = analysis/{stable_id}/result.md 존재로 serve-time 파생** (저장 플래그 동기화 의존 제거)
- 분석 자체는 구독(Claude Code rfp-analyzer)로 사람이 트리거
- 분석 입력 우선순위: 파일명 제안요청서/과업지시서/공고 포함 PDF 우선

## 컴포넌트
- 신설: dashboard/app.py(Flask), dashboard/datasource.py(generate.py 흡수), scraper/core/converter.py(win32 변환)
- 수정: dashboard/index.html(2탭+버튼+폴링), scraper/core/runner.py(자동다운로드 제거), g2b.py/json_store.py(첨부URL 저장), scripts/run_dashboard.bat(Flask 실행)
- 폐기: dashboard/generate.py, data.json

## API 엔드포인트
- GET /api/announcements (목록+상태)
- POST /api/download/<stable_id> (백그라운드 다운로드+변환)
- GET /api/status/<stable_id> (진행상태)
- GET /api/report/<stable_id> (result.md 렌더)

## 버튼 상태머신
미다운로드 → 다운로드중 → 분석대기 → 분석완료 / (실패→재시도)

## win32 변환 주의 (구현 필수)
- RegisterModule("FilePathCheckDLL","FilePathCheckerModule")로 보안 팝업 차단
- 백그라운드 스레드에서 pythoncom.CoInitialize() 필요
- hwp.SaveAs(경로,"PDF"), 작업 후 hwp.Quit()
- pywin32 의존성 추가, 한글 미설치/COM오류 시 graceful 실패

## Consequences
- 얻는 것: 관심 공고만 선별 다운로드·변환, 항상 최신 화면, 불필요 첨부 미수집, 변환 충실도 높음
- 어려워지는 것: 실행이 서버 켜기로 바뀜(run_dashboard.bat 흡수), 한글 설치 의존, 변경 범위 큼
- 되돌리기: 부분적 (수집/저장 JSON은 유지, 대시보드 계층만 교체)

## 구현 단계 (권장 분할)
1. win32 변환 모듈 (converter.py) — 최우선 리스크 검증
2. 수집 자동다운로드 제거 + 첨부 URL 저장
3. Flask 앱 + 탭1 목록/다운로드 버튼
4. 탭2 리포트 + 분석 연결

## 검증 리스크
- win32 한글 자동화 안정성(보안모듈/COM스레드), 한글 미설치 환경 처리, HWPX 변환 지원

## 관련 문서
- docs/sessions/2026-06-02.md (분석+웹앱 스펙)
- docs/ADR-003-json-canonical-store.md (JSON 정본)
