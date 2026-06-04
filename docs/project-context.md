# Project Context

This file records project-specific conventions and facts.
It is **not** a coding style guide — for agent behavior guidelines, see `CLAUDE.md` at the repo root.

---

## Session Startup

**세션 시작 시 `docs/sessions/` 의 최신 세션 로그를 읽어 맥락을 파악한다.**

1. 직전 세션 로그(날짜 기준 가장 최근 파일)를 확인해 진행 중인 작업이 있으면 사용자에게 알린다.
2. 새 세션의 주요 결정·진행 내역은 `docs/sessions/YYYY-MM-DD.md` 형식으로 저장한다.

**세션 로그 저장 경로:** `docs/sessions/YYYY-MM-DD.md`

---

## Git Conventions

### Commit Message Format

```
<type>: <short summary>

- optional bullet describing what changed
```

| type | when to use |
|------|-------------|
| `feat` | new feature or capability |
| `fix` | bug fix |
| `refactor` | restructuring with no behavior change |
| `chore` | config, dependencies, tooling, docs |
| `docs` | documentation only |

### Hard Rules

- Never commit `.env`
- Never commit `scraper/output/` or `scraper/logs/`
- Never commit `analysis/` (분석 산출물은 로컬 전용)

---

## Reference Docs

| File | Purpose |
|------|---------|
| `docs/architecture/README.md` | 현재 시스템 구조 개요 (디렉토리·파이프라인·컴포넌트 역할) |
| `docs/architecture/ADR-001~004.md` | 기술 결정의 배경·이유 기록 |
| `docs/analysis-workflow.md` | 공고 분석 실행 절차 (대시보드 → rfp-analyzer) |
| `scraper/config.yaml` | 수집 설정 단일 진실 공급원 |
