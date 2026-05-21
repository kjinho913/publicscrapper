# CLAUDE.md

Behavioral guidelines to reduce common LLM coding mistakes. Merge with project-specific instructions as needed.

**Tradeoff:** These guidelines bias toward caution over speed. For trivial tasks, use judgment.

## 0. Session Startup and Progress Tracking

**Always read `WORKLOG.md` first at the start of a session:**

1. If there is a task in progress under `## Current Task`, notify the user and confirm whether to resume it or start a new one.
2. If `## Current Task` is empty and items exist under `## Next Up`, summarize and report the contents to the user.

**Update `WORKLOG.md` at the following trigger points during execution:**

- **At task initiation:** Record a timestamp and its sub-steps under `## Current Task`.
- **Upon sub-step completion:** Update the status of that specific line to `done`.
- **Upon full task completion:** Move the entry to `## Completed` and initialize `## Current Task` to `_None_`.
- **When the user mentions a new task:** Append it to `## Next Up`.
- **At session startup:** Add a new session log entry below the `---` delimiter.

**Formatting Rules:**

- **Timestamp:** `[YYYY-MM-DD HH:MM]`
- **Sub-step Status:** `pending` / `IN PROGRESS` / `done`
- Do **never** delete the `---` delimiter or the section headers above it.

**CRITICAL:** Sub-steps must be recorded **prior to** execution. This ensures that in the event of a system crash, the subsequent session can precisely identify where the process halted.

---

## 1. Think Before Coding

**Don't assume. Don't hide confusion. Surface tradeoffs.**

Before implementing:

- State your assumptions explicitly. If uncertain, ask.
- If multiple interpretations exist, present them — don't pick silently.
- If a simpler approach exists, say so. Push back when warranted.
- If something is unclear, stop. Name what's confusing. Ask.

## 2. Simplicity First

**Minimum code that solves the problem. Nothing speculative.**

- No features beyond what was asked.
- No abstractions for single-use code.
- No "flexibility" or "configurability" that wasn't requested.
- No error handling for impossible scenarios.
- If you write 200 lines and it could be 50, rewrite it.

Ask yourself: "Would a senior engineer say this is overcomplicated?" If yes, simplify.

## 3. Surgical Changes

**Touch only what you must. Clean up only your own mess.**

When editing existing code:

- Don't "improve" adjacent code, comments, or formatting.
- Don't refactor things that aren't broken.
- Match existing style, even if you'd do it differently.
- If you notice unrelated dead code, mention it — don't delete it.

When your changes create orphans:

- Remove imports/variables/functions that YOUR changes made unused.
- Don't remove pre-existing dead code unless asked.

The test: Every changed line should trace directly to the user's request.

## 4. Goal-Driven Execution

**Define success criteria. Loop until verified.**

Transform tasks into verifiable goals:

- "Add validation" → "Write tests for invalid inputs, then make them pass"
- "Fix the bug" → "Write a test that reproduces it, then make it pass"
- "Refactor X" → "Ensure tests pass before and after"

For multi-step tasks, state a brief plan:

```
1. [Step] → verify: [check]
2. [Step] → verify: [check]
3. [Step] → verify: [check]
```

Strong success criteria let you loop independently. Weak criteria ("make it work") require constant clarification.

---

**These guidelines are working if:** fewer unnecessary changes in diffs, fewer rewrites due to overcomplication, and clarifying questions come before implementation rather than after mistakes.

## 5. Git Workflow

**Every completed task must end with a commit and push.**

### When to Commit

- **On task completion:** Commit immediately after moving the current task to `## Completed` in WORKLOG.md.
- **One commit per logical task:** Regardless of how many files were changed.
- **Always push:** Run `git push` right after committing. Never leave work only in local.

### Commit Message Format

```
<type>: <short summary>

- optional bullet describing what changed
```

**Types:**

| type | when to use |
|------|-------------|
| `feat` | new feature or capability |
| `fix` | bug fix |
| `refactor` | restructuring with no behavior change |
| `chore` | config, dependencies, tooling, docs |
| `docs` | documentation only |

**Examples:**
```
feat: add deadline parsing to NIA scraper
fix: warn correctly when G2B API key is missing
refactor: consolidate app/ and scrapers/ into core/
chore: add python-dotenv and move API key to .env
```

### Hard Rules

- Never commit `.env` — always run `git status` and verify before staging.
- Never commit `output/` or `logs/`.
- Never commit a broken state (missing imports, half-written functions).

### Execution Order (after every task)

```bash
git status                  # 1. verify .env is not listed
git add <changed files>     # 2. stage relevant files only
git commit -m "type: summary"  # 3. commit
git push                    # 4. push to remote
```

Always include `WORKLOG.md` in the commit.

## 6. Reference Docs

- `docs/architecture.md` : System architecture diagram and information
- `docs/progress.md` : Development progress summary document
