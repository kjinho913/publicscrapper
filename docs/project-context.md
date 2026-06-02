# Project Context

This file records project-specific conventions and facts.
It is **not** a coding style guide — for agent behavior guidelines, see `CLAUDE.md` at the repo root.

---

## Session Startup

**Always read `WORKLOG.md` first at the start of a session:**

1. If a task is in progress under `## Current Task`, notify the user and confirm whether to resume or start a new one.
2. If `## Current Task` is empty and items exist under `## Next Up`, summarize them.

**Update `WORKLOG.md` at these trigger points:**

- Task initiated → record timestamp and sub-steps under `## Current Task`
- Sub-step done → update that line's status to `done`
- Task complete → move entry to `## Completed`, reset `## Current Task` to `_None_`
- New task mentioned by user → append to `## Next Up`
- Session start → add a new session log entry below the `---` delimiter

**Timestamp format:** `[YYYY-MM-DD HH:MM]`
**Sub-step status values:** `pending` / `IN PROGRESS` / `done`
**Never delete** the `---` delimiter or section headers.

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
- Never commit `output/` or `logs/`
- Always include `WORKLOG.md` in the commit
- Always `git push` after committing

---

## Reference Docs

| File | Purpose |
|------|---------|
| `docs/architecture.md` | System architecture diagram and information |
| `docs/progress.md` | Development progress summary |
| `config.yaml` | Single source of truth for all scraper configuration |
