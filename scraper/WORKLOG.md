# Work Log

## Current Task
_None_



## Completed
[2026-05-21] G2B 공고링크·첨부파일 API 직접 수집으로 전환
- Step 1: G2B selectSubFrame.do URL → bidNtceDtlUrl (API 제공) 로 교체: done
- Step 2: fetch_detail() Playwright 제거 → ntceSpecDocUrl1~10 API 직접 파싱: done
- Step 3: base.py FETCH_DETAIL 플래그 추가 (no-op detail 시 sleep 제거): done
- Step 4: 검증 (100건 수집, 193개 첨부파일 다운로드, 66건 Excel): done
- Step 5: 커밋 및 푸시: done
[2026-05-21] G2B/ETRI Playwright 버그 수정
- Step 1: playwright_helper.py — page.frames() → page.frames (property): done
- Step 2: etri.py — _fetch_page() 목록 수집을 playwright_browser.post_html()로 전환: done
- Step 3: G2B 테스트 (100건 수집 / 67건 필터): done
- Step 4: ETRI 테스트 (10건 수집 / 타임아웃 해소): done
- Step 5: 커밋 및 푸시: done
[2026-05-21] Playwright 전환 구현
- Step 1: requirements.txt playwright 추가: done
- Step 2: core/playwright_helper.py 신규 작성: done
- Step 3: core/scrapers/base.py 확장 (USE_PLAYWRIGHT_FOR_DETAIL, _get_detail_html): done
- Step 4: core/runner.py PlaywrightBrowser 관리 추가: done
- Step 5: nipa/mss/nia fetch_detail → _get_detail_html 사용: done
- Step 6: g2b fetch_detail → get_frame_html 사용: done
- Step 7: etri fetch_detail 신규 구현 → post_html 사용: done
- Step 8: 테스트 (nia, nipa): done
- Step 9: 커밋 및 푸시: done
[2026-05-21] NIA 3개 버그 수정
- Step 1: excel_writer.py — save_announcements 배치 내 중복 제거: done
- Step 2: nia.py — fetch_list 페이지 반복 감지 시 중단: done
- Step 3: runner.py — _attachment_urls URL 중복 제거: done
- Step 4: 커밋 및 푸시: done
- 잔존 이슈: NIA 일부 공고(29410, 29408 등) 파일 목록 AJAX 지연로딩 → 정적 HTML 수집 시 누락
[2026-05-21] 이미 수집한 공고의 첨부파일 재다운로드 방지
- Step 1: excel_writer.py — get_existing_announcement_keys() 함수 추가: done
- Step 2: runner.py — 첨부파일 루프에서 기존 공고 건너뜀 로직 추가: done
- Step 3: 커밋 및 푸시: done
[2026-05-21] output 폴더 구조 변경 (attachments/<site>/<공고번호> → <site>/<날짜>)
- Step 1: config.yaml download_dir 수정 (./output/attachments → ./output): done
- Step 2: runner.py dest 경로를 att_base_dir/source/YYYY-MM-DD 로 변경: done
- Step 3: WORKLOG.md 완료 처리 및 커밋: done
[2026-05-21] 디렉토리 구조 재설계 (app/ + scrapers/ → core/)
- Step 1: core/ 패키지 생성 (내용 무변경 파일 복사): done
- Step 2: core/runner.py 작성 (app/site_runner.py import 수정): done
- Step 3: core/scheduler.py 작성 (app/main.py 로직 추출): done
- Step 4: config.yaml 루트로 이동 (app/config.yaml → config.yaml): done
- Step 5: main.py 단일 진입점으로 통합 재작성: done
- Step 6: 구 디렉토리 삭제 (app/, scrapers/, __pycache__): done

[2026-05-19 17:00] 스크래퍼 5개 개선 작업 (7 Step)
- Step 1: MSS cbIdx=86→310 (공고문 게시판): done
- Step 1.5: LIST_URL/PAGE_PARAM/API_BASE를 config.yaml sites 섹션으로 이동: done
- Step 2: 사이트별 수집 통계 표 출력 (main.py): done
- Step 3: G2B 재실행 확인 + ETRI 활성화·셀렉터 검증: done
- Step 4: 상세 페이지 디버그 도구 + 첨부파일 SEL_FILES 수정: done
- Step 5: 필터링 개선 (제외 키워드 + 사이트별 설정): done
- Step 6: NIA JS 렌더링 대응 (playwright): done
- Step 7: 문서 업데이트 (README.md, architecture.md, progress.md): done

[2026-05-19] 스크래퍼 오류 분석 및 수정
- NIPA: LIST_URL, PAGE_PARAM, SEL_ROWS, SEL_DATE, SEL_ORG, SEL_TITLE_LINK, URL 생성 로직 수정 → 수집 정상
- MSS: SEL_ROWS, SEL_TITLE_LINK, SEL_DATE, SEL_ORG 수정 + onclick bcIdx 추출로 URL 생성 → 수집 정상
- G2B: API_BASE 신규 엔드포인트 + inqryDiv=1 파라미터 추가
- NIA: cbIdx=75826→78336 수정 ("잘못된 접근" 해소), JS 렌더링 0건은 별도 이슈

## Next Up
_Nothing queued_

---
<!-- session log below — newest entries at top -->
[2026-05-21] G2B 공고링크/첨부파일 전면 개선. selectSubFrame.do(404) → bidNtceDtlUrl. Playwright 제거 후 API ntceSpecDocUrl 직접 파싱. 실행시간 6분→50초, 첨부파일 0→193개.
[2026-05-21] G2B/ETRI 버그 수정. G2B: page.frames() → page.frames. ETRI: 목록 수집 Playwright post_html 전환으로 타임아웃 해소. G2B 100건/67건, ETRI 10건 수집 확인.
[2026-05-21] Playwright 전환 완료. NIA/NIPA 테스트 통과 (Playwright 브라우저 정상 시작·종료, 첨부파일 수집 확인).
[2026-05-21] NIA 버그 3건 수정: 페이지네이션 반복 감지, 배치 내 중복 제거, URL 중복 제거. 수집 50→10건, Excel 40→8건으로 정상화.
[2026-05-21] 이미 수집한 공고 첨부파일 재다운로드 방지 구현. Excel 기존 키 기반 건너뜀.
[2026-05-21] output 폴더 구조 변경. attachments/<site>/<공고번호> → <site>/<YYYY-MM-DD> 로 단순화.
[2026-05-21] 디렉토리 구조 재설계 완료. app/ + scrapers/ → core/ 통합, main.py 단일 진입점으로 재작성.
[2026-05-19] 7-Step 개선 계획 수립. Step 1 시작.
[2026-05-19] 세션 재개. 오류 분석 완료, 수정 단계 진행 중.
