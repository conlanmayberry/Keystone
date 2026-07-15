# MegaChud

Self-improving autonomous AI operating system. This repo currently
implements **Phase 1** (reliable core: orchestrator, sandboxed tools,
persistence, logging, evaluation, dashboard) and **Phase 2** (memory:
deterministic reflection, episodic/semantic/user memory, local semantic
retrieval, and an Obsidian vault). See the planning docs for the full
picture:

- [Master_Specification.md](Master_Specification.md) — vision, design
  principles, and the full set of components the platform grows into.
- [Implementation_Plan.md](Implementation_Plan.md) — the 5-phase roadmap.
  This repo covers Phases 1–2.
- [Engineering_Standards.md](Engineering_Standards.md) — language,
  architecture, logging, and quality standards followed throughout.

Phase 1 deliberately ships **no internet access and no
transaction/financial tools** — only local, sandboxed file and shell
tools. Every tool declares a `risk_level` (`low` / `medium` /
`high_irreversible`), and any `high_irreversible` tool call is routed
through a human approval gate before it runs. This mechanism is fully
built and tested now (see `tests/fixtures/dummy_tools.py`) so that later
phases can add real internet-access and money-related tools — an explicit
acceptance criterion for the finished product — without reworking the
orchestrator.

## Setup

```
py -3.12 -m venv .venv
.venv/Scripts/pip install -e ".[dev]"
python scripts/init_db.py
```

## Run

```
.venv/Scripts/python -m megachud.cli serve
```

Or directly with uvicorn (factory pattern, so importing the module never
has side effects — see the note in `src/megachud/api/app.py`):

```
.venv/Scripts/python -m uvicorn megachud.api.app:create_app --factory --reload
```

Then open http://127.0.0.1:8000. The dashboard lets you submit a task (a
title, prompt, and an explicit JSON list of tool calls — there is no
autonomous planner yet), watch the live activity feed over WebSocket,
review task history, approve/deny any pending `high_irreversible` tool
calls, and browse/search/add memory in the Memory Browser panel.

Every completed task automatically generates a deterministic `Reflection`
and one or more `MemoryEntry` rows, mirrored as Markdown notes under
`vault/` — open that folder directly in the Obsidian app to browse them
(frontmatter properties, `[[wikilinks]]` between a task and its memory,
tag search).

## Smoke tests without the dashboard

```
.venv/Scripts/python scripts/run_dummy_task.py
```

Runs a real 2-step task end-to-end against the dev DB, plus a deliberate
Python-syntax-error task to show the evaluation engine catching a bug that
the tool call itself reported as "successful".

```
.venv/Scripts/python scripts/run_memory_demo.py record
.venv/Scripts/python scripts/run_memory_demo.py recall
```

Run as two **separate process invocations** — proves memory recall
survives a cold process, using only what's persisted to disk (Phase 2's
acceptance criterion).

```
.venv/Scripts/python scripts/reindex_vault.py
```

Re-reads every note under `vault/` and upserts it back into the DB —
human edits made directly in Obsidian win.

## Tests

```
.venv/Scripts/python -m pytest
```

## Architecture

### Phase 1 — reliable core
- **Orchestrator** (`orchestrator/`): runs a finite, caller-supplied plan
  (list of tool calls) — no autonomous re-planning loop yet, so there's no
  runaway-agent risk at this phase.
- **Tools** (`tools/`): `read_file`, `write_file`, `shell_exec`, all
  confined to `workspace/` via `workspace/sandbox.py`. No `shell=True`,
  command allowlist/denylist, subprocess timeouts.
- **Approval gate** (`orchestrator/approval_gate.py`): blocks execution of
  any `high_irreversible` tool call until a human resolves it via the
  dashboard or it times out.
- **Evaluation** (`evaluation/`): a task is only marked `succeeded` if
  real checks pass (all tool calls succeeded, `ast.parse()` on touched
  `.py` files, an optional configured test command) — never assumed.
- **Events** (`events/`): every tool call, approval decision, and
  evaluation is written to the `events` table and fanned out live over
  `/ws/live`.

### Phase 2 — memory
- **Reflection** (`reflection/`): `DeterministicReflectionGenerator` derives
  what worked/failed/wrong assumptions/what should change from evaluation
  checks, events, and task state — no LLM call. `ReflectionGenerator` is an
  explicit swap point for a future LLM-backed implementation.
  `TaskCompletionHandler` is wired as `EventLogger`'s optional `on_event`
  callback, so the pipeline fires identically whether triggered from the
  API or a standalone script.
- **Memory** (`memory/`): a single `MemoryEntry` table (`episodic` /
  `semantic` / `user`), embedded via a stateless local `HashingVectorizer`
  (no fitting, no network, no model download). `memory/retrieval.py`
  ranks by cosine similarity via one vectorized numpy matmul.
- **Obsidian** (`obsidian/`): mirrors every memory entry and completed task
  as Markdown with YAML frontmatter under `vault/`, with `[[wikilinks]]`
  between a task and its memory. `reindex_vault()` re-reads the vault back
  into the DB — human edits win.

### Dashboard
- **`api/`, `web/static/`**: FastAPI + plain HTML/JS, no build step. Panels:
  New Task, Working Summary, Pending Approvals, Live Activity, Task
  History, Memory Browser.

Persistence, config, and safety-guardrail details are documented inline
in `src/megachud/config.py`, `src/megachud/db.py`, and
`src/megachud/tools/shell_tool.py`.
