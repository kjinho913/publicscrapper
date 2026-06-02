# ADR-003: 수집 기록 원본을 JSON 단일 저장소로 전환

- **Date:** 2026-06-02
- **Status:** Accepted

## Context

Excel 누적 방식(announcements.xlsx, 사이트별 시트, append-only)이 과거·타사이트 데이터를 섞어 쌓아
대시보드 혼란과 마감일 빈값(과거 잔존 데이터) 문제를 유발했다.
v1.0은 나라장터 단일이며, 최종 목표(AI 분석 기반 의사결정 지원)를 위해 중복방지·분석/판단 상태 추적이 필요하다.

## Decision

- **캐논(정본) = `scraper/output/announcements.json`** (stable_id를 키로 하는 dict 구조)
- **캐논 키 = URL기반 stable_id**: NIPA `nttNo` / 나라장터 입찰공고 `bidPbancNo` / 나라장터 사전규격 `bfSpecRegNo`
- `derive_stable_id()`를 공용 모듈(`scraper/core/ids.py`)로 이동 → 스크래퍼가 수집 시점에 stable_id 기록, 대시보드도 동일 사용
- **재수집 = upsert**: 변동필드(공고명/마감일/예산/내용/단계/최종수집일시) 갱신, 보존필드(최초수집일시/analyzed/분석경로/판단상태/첨부파일) 유지
- 중복판정(재다운로드 스킵)을 JSON 기반(`json_store.existing_ids()`)으로 전환
- 대시보드 generate.py가 Excel 대신 announcements.json 읽기
- Excel 쓰기 경로 제거(excel_writer.py 파일은 보존 — export backlog 재활용)
- 기존 announcements.xlsx는 legacy로 이름 변경 보관, JSON 저장소는 새로 시작. output/analysis 폴더는 유지

## 레코드 스키마
stable_id, 공고번호, 공고명, 발주기관, 출처사이트, 단계(입찰공고|사전규격), 공고일, 마감일시,
예산금액, 내용요약, 공고링크, 첨부파일수, 첨부파일경로, 최초수집일시, 최종수집일시,
analyzed(bool), 분석경로, 판단상태(미검토|관심|참여검토|제외)

## 변경 대상 파일
- 신설: scraper/core/json_store.py (load_store/upsert/existing_ids)
- 신설: scraper/core/ids.py (derive_stable_id 공용화, 3패턴)
- 수정: scraper/core/scrapers/g2b.py (stable_id·단계 기록)
- 수정: scraper/core/runner.py (중복판정 JSON 기반)
- 수정: scraper/main.py (save_announcements → json_store.upsert)
- 수정: dashboard/generate.py (Excel → JSON 읽기, ids.py 재사용)
- 보존: scraper/core/excel_writer.py (호출 제거, export backlog용)
- 정리: scraper/config.yaml output 섹션

## Consequences
- 얻는 것: 누적/혼재 해소, 안정 키 중복판정, 판단·분석 추적, JSON 열람 가능, tmp/Excel 이원구조 단순화
- 어려워지는 것: Excel 즉시열람 편의 상실(export backlog로 보완), 변경 범위 6개 파일
- 되돌리기: 부분적 (excel_writer.py 보존)

## 관련 문서
- docs/sessions/2026-06-02.md (데이터 저장 방식 결정 경위)
- docs/ADR-002-g2b-v1-pipeline.md (수집 파이프라인)
