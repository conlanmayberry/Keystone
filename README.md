# MegaChud

Self-improving autonomous AI operating system. This repo currently
implements **Phase 1** (reliable core: orchestrator, sandboxed tools,
persistence, logging, evaluation, dashboard), **Phase 2** (memory:
deterministic reflection, episodic/semantic/user memory, local semantic
retrieval, and an Obsidian vault), **Phase 3** (improvement: strategy/
workflow engine, experiments, curiosity, bottleneck detection), and
**Phase 4** (optimization: model routing infrastructure, analytics,
hourly/weekly reviews). See the planning docs for the full picture:

- [Master_Specification.md](Master_Specification.md) — vision, design
  principles, and the full set of components the platform grows into.
- [Implementation_Plan.md](Implementation_Plan.md) — the 5-phase roadmap.
  This repo covers Phases 1–4.
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
orchestrator. Phase 3's Curiosity Engine and Phase 4's Model Selection
Engine both deliberately stay on the local side of that same boundary:
curiosity searches only existing memory (no real web search), and model
routing is a config-driven decision framework with no LLM call anywhere
in the codebase yet — both are explicit swap points for real
implementations later.

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
calls, browse/search/add memory, invoke strategies and manage
experiments/promotions, answer curiosity questions, scan for bottlenecks,
and review analytics/hourly/weekly reports plus a model-routing simulator.

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

```
.venv/Scripts/python scripts/run_experiment_demo.py
```

Seeds a control + variant Strategy for the same workflow, runs both
through a real Orchestrator with differing outcomes, evaluates the
resulting Experiment, and shows the PromotionRequest it creates — proves
strategy metrics, experiment comparison, and promotion all work end to
end against the real dev DB (Phase 3's acceptance criterion).

```
.venv/Scripts/python scripts/run_optimization_demo.py
```

Simulates a few model-routing decisions (logged as `Event` rows, no real
LLM call), builds an analytics report, and generates + persists an
hourly and a weekly review — showing the honest `cost_data_available:
False` state throughout, since no LLM call site exists in the codebase
yet. Run `run_experiment_demo.py` first so there's real activity to
report on.

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
  `/ws/live`. `EventDispatcher` (Phase 3) composes multiple `on_event`
  handlers into the one callback `EventLogger` accepts, so `EventLogger`
  itself never grows new responsibilities as later phases add handlers.

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

### Phase 3 — improvement
- **Strategy** (`strategy/`): a "workflow" is not a separate table — it's
  the set of `Strategy` rows sharing `workflow_name` with exactly one
  `is_active=True`. `strategy/invoker.py::render_plan` substitutes
  `{param}` placeholders by recursing through the parsed plan template and
  formatting leaf strings only (not by naively `.format()`-ing the whole
  serialized JSON, which would crash on any real template). `strategy/
  metrics.py::StrategyMetricsHandler` updates rolling
  sample_count/success_count/mean_duration_ms on task completion via the
  same `EventDispatcher` hook.
- **Experiment + Promotion** (`experiment/`, `strategy/promotion.py`):
  `evaluate_experiment` is a boring success-rate-delta +
  minimum-sample-size gate (no significance testing). A concluding
  `PROMOTE_VARIANT` recommendation creates a `PromotionRequest` — a human
  must approve it before `Strategy.is_active` ever changes.
  `PromotionRequest` is deliberately separate from `ApprovalRequest`: the
  latter is a blocking, in-task-execution mechanism tied to
  `ApprovalGate`; a promotion is an out-of-band review action with no task
  waiting on it.
- **Bottleneck detection** (`bottleneck/`): three deterministic
  aggregation queries (tool failure rate, high-retry tasks, declining
  strategy success), computed on demand — not persisted, same as
  Analytics. Feeds `propose_experiment_from_bottleneck`.
- **Curiosity** (`curiosity/`): local-only — when a reflection is flagged
  `become_long_term_knowledge` and no sufficiently similar memory already
  exists, raises a `PendingQuestion` and `ResearchObjective`s. Explicitly
  filters out the current task's own just-created memory entries from the
  similarity check (otherwise a task's own fresh reflection would always
  "explain itself" and curiosity would never trigger).

### Phase 4 — optimization
- **Model Selection Engine** (`routing/`): `ConfiguredModelRouter` picks
  the cheapest configured model profile meeting a quality target — pure
  config lookup and arithmetic, no LLM call anywhere. `ModelRouter` is an
  explicit swap point for a real routing implementation later. Decisions
  are logged as `Event(event_type="model_routing_decision")` — reusing
  the existing structured log rather than a new table.
- **Analytics** (`analytics/`): computed on demand (same pattern as
  `BottleneckFinding`), reporting task/tool/workflow/experiment counts and
  rates over a window. `cost_data_available` is honestly `False` until a
  real LLM call populates `Event.cost_usd` — never fabricated.
- **Reviews** (`review/`, `models/review.py`): unlike Analytics, a
  `Review` **is** persisted — a point-in-time record worth keeping.
  `generate_hourly_review`/`generate_weekly_review` build a deterministic
  structured report (accomplishments, blockers, learning, costs; weekly
  adds workflow evolution, strategy effectiveness, model routing summary,
  and recommendations reused directly from `bottleneck.finder`) — no LLM
  narration.

### Dashboard
- **`api/`, `web/static/`**: FastAPI + plain HTML/JS, no build step.
  Panels: New Task, Working Summary, Pending Approvals, Live Activity,
  Task History, Memory Browser, Strategy/Workflow Browser, Experiment
  Browser (with inline Promotion approvals), Curiosity, Bottleneck
  Findings, Analytics, Reviews, Model Routing.

Persistence, config, and safety-guardrail details are documented inline
in `src/megachud/config.py`, `src/megachud/db.py`, and
`src/megachud/tools/shell_tool.py`.
