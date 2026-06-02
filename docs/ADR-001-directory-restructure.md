# ADR-001: 디렉토리 구조 개선

- **Date:** 2026-06-01
- **Status:** Accepted

## Decision

아래 4가지 구조 변경을 적용한다.

1. `scraper/docs/` → `docs/`로 통합
2. 루트 `output/` → `analysis/`로 이름 변경 (`scraper/output/`은 유지)
3. 루트에 `scripts/` 폴더 신규 생성 — 실행 진입점 통합
4. `scraper/.claude/` 삭제 → 루트 `.claude/`로 통합

## Reasoning

비개발자 운영자가 프로젝트 구조를 한눈에 파악할 수 있어야 하고,
코드 변경을 최소화하면서 혼란 요소를 제거하는 것이 목표.

- `scraper/output/`은 config.yaml 및 main.py에 하드코딩된 경로이므로 이동 비용이 크다 → 유지
- 루트 `output/`은 rfp-analyzer 전용이므로 목적이 드러나는 `analysis/`로 명확화
- `scraper/docs/`의 architecture.md, progress.md는 프로젝트 전체 문맥 문서이므로 루트 docs/로 통합

## Consequences

| 변경                              | 코드 수정 필요 여부        |
| --------------------------------- | -------------------------- |
| `scraper/docs/` → `docs/` 통합    | 없음                       |
| `output/` → `analysis/` 이름 변경 | rfp-analyzer 저장 경로 1곳 |
| `scripts/` 신규 생성              | 없음                       |
| `scraper/.claude/` 삭제           | 루트 설정에 권한 병합      |

## 최종 구조

```
webscrap/
├── analysis/          ← (구 output/)
├── dashboard/
├── docs/              ← 문서 단일화
├── scripts/           ← 실행 진입점 통합
├── scraper/
│   ├── logs/          ← 유지
│   └── output/        ← 유지
└── tasks/
```
