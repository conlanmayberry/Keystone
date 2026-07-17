# MegaChud

Self-improving autonomous AI operating system. This repo implements all
**5 phases** of the roadmap: **Phase 1** (reliable core), **Phase 2**
(memory), **Phase 3** (improvement: strategy/workflow engine, experiments,
curiosity, bottleneck detection), **Phase 4** (optimization: model routing
infrastructure, analytics, hourly/weekly reviews), and **Phase 5**
(platform: dynamic plugin loading, structural multi-agent/multi-project
readiness, advanced dashboards), plus a first real **LLM integration**
(Anthropic Claude) layered on top once all 5 phases were done — see
"LLM Integration" below. See the planning docs for the full picture:

- [Master_Specification.md](Master_Specification.md) — vision, design
  principles, and the full set of components the platform grows into.
- [Implementation_Plan.md](Implementation_Plan.md) — the 5-phase roadmap.
  This repo covers all 5 phases.
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
orchestrator. Curiosity still searches only existing local memory (no
real web search), and the Model Selection Engine (`routing/`) is still a
config-driven decision framework with no LLM call inside it anywhere —
picking a model is still pure arithmetic, never itself an LLM call. What
*has* changed since Phase 5: three other components (reflection
generation, task planning, curiosity question/objective text) now have
real Anthropic Claude-backed implementations, gated entirely behind
whether `ANTHROPIC_API_KEY` is configured — see "LLM Integration" below.
Phase 5's plugin system was the first exception to the local-only
boundary: dynamic runtime loading of external Python code is real,
deliberately scoped to local-only, explicit-opt-in sources (see
"Plugins" below).

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
title, prompt, and either an explicit JSON list of tool calls or, if an
`ANTHROPIC_API_KEY` is configured, an "Auto-plan (LLM)" checkbox that has
the configured LLM produce the plan instead), watch the live activity
feed over WebSocket, review task history, approve/deny any pending
`high_irreversible` tool calls, browse/search/add memory, invoke
strategies and manage experiments/promotions, answer curiosity questions,
scan for bottlenecks, and review analytics/hourly/weekly reports plus a
model-routing simulator, browse loaded plugins, and filter Task
History/Analytics by agent.

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

Simulates a few model-routing decisions (logged as `Event` rows — model
*selection* itself is still pure config arithmetic, no LLM call), builds
an analytics report, and generates + persists an hourly and a weekly
review. With no `ANTHROPIC_API_KEY` configured this honestly shows
`cost_data_available: False` throughout, since nothing has populated
`Event.cost_usd` yet; see `run_llm_demo.py` below for the real-cost path.
Run `run_experiment_demo.py` first so there's real activity to report on.

```
.venv/Scripts/python scripts/run_platform_demo.py
```

Force-enables the shipped example plugin, loads it, and runs a real task
through the orchestrator using the plugin-registered `uppercase_text`
tool — proving a plugin's `Tool` executes with zero special-casing (the
approval gate already applies uniformly regardless of a tool's origin).
Also prints the seeded default `Agent` row (Phase 5's structural
multi-agent readiness).

```
.venv/Scripts/python scripts/run_llm_demo.py
```

Run this once before adding a real key to `.env` (proves nothing crashes
and every LLM-backed component falls back to its deterministic
predecessor) and once after (proves all 3 LLM swap-points — reflection,
planning, curiosity — plus real cost/token tracking work end to end
against the live Anthropic API). See "LLM Integration" below for setup.

## Plugins

See [plugins/README.md](plugins/README.md) for the full mechanism and
safety model. Short version: dynamic runtime loading of external Python
code is real (unlike every other capability boundary in this project,
which stayed local-only) but deliberately scoped — local-only discovery
(a `plugins/` directory, or already pip-installed packages), explicit
config allow-listing (nothing loads unless named), full `Event`-logged
observability, and `Tool.risk_level` enforcement before a plugin tool
ever reaches the real tool set. Python has no in-process sandbox — only
enable plugins you trust.

## LLM Integration

The first real LLM calls in this codebase, added after all 5 phases were
complete. `LLMClient` (`src/megachud/llm/client.py`) is a 4th ABC
swap-point alongside `Tool`, `ReflectionGenerator`, and `ModelRouter` —
`AnthropicLLMClient` is the one real implementation, backed by the
`anthropic` SDK.

**Setup**: copy [.env.example](.env.example) to `.env` and set
`ANTHROPIC_API_KEY=sk-ant-...`. `Settings.load()` picks it up
automatically via a pure `dotenv_values()`-based loader (never
`load_dotenv()`, so nothing mutates `os.environ` globally); a real
environment variable always takes precedence over `.env`. The key is
stored as a `pydantic.SecretStr` and never appears in a `repr()`/`str()`
of `Settings`. **No real key is ever committed** — `.env` is gitignored,
and `.env.example` ships with an empty value.

**Graceful degradation is the whole design.** `create_app()` never
raises and behaves identically to before this integration when no key is
configured — every LLM-backed component conditionally falls back to its
original deterministic implementation:

- **Reflection** (`reflection/llm_generator.py::LLMReflectionGenerator`):
  fills the `ReflectionGenerator` swap-point only if no plugin already
  claimed it. Falls back to `DeterministicReflectionGenerator` on any
  `LLMError` or malformed response — `generate()` never raises.
- **Task planning** (`orchestrator/llm_planner.py::LLMTaskPlanner`): a
  genuinely new capability, not a fallback of an existing one. One-shot
  only — the LLM produces a complete tool-call plan in a single call,
  which then runs through the existing `Orchestrator.run_task`
  completely unchanged (same finite-plan execution, same evaluation,
  same approval gate). There is deliberately no iterative/ReAct
  re-planning loop, preserving the no-runaway-agent property every
  earlier phase relied on. Exposed via `POST /tasks` with
  `"auto_plan": true` instead of a supplied `tool_calls` list, and the
  dashboard's New Task panel has a matching "Auto-plan (LLM)" checkbox.
  A hallucinated tool name or invalid args is rejected (`422`) via
  `ToolRegistry.get()` + `Tool.validate_args()` — the same validation the
  orchestrator would eventually hit, performed before any `Task` row is
  created — with no retry/re-prompt. `503` if unconfigured, `502` on a
  real API request failure.
- **Curiosity text** (`curiosity/llm_generator.py`): swaps in richer
  LLM-authored question/objective wording; every other part of
  `CuriosityHandler` (real local memory search, the self-match filter,
  the `become_long_term_knowledge` gate, the similarity threshold) is
  untouched. Falls back to the original template strings on failure.

**Cost/token tracking is now real.** `Event.cost_usd`/`tokens_input`/
`tokens_output` (unused since Phase 1) are populated on every successful
LLM call via `routing/engine.py::compute_cost_usd`, logged as
`Event(event_type="llm_call")`. Costs are **never fabricated** — an event
is only logged when a component actually made a real call and got real
usage numbers back (e.g. the deterministic curiosity path always reports
0 tokens and logs nothing). This is what finally makes Analytics'
`cost_data_available` become `True`.

Model IDs and approximate per-1K-token pricing live in
`config/default.yaml`'s `model_routing.profiles` (verify current pricing
before relying on it) and are shared by `ConfiguredModelRouter` and every
LLM consumer's cost computation. Per-consumer model choice and
`max_tokens` live in the `llm:` config section
(`default_reflection_model`, `default_planner_model`,
`default_curiosity_model`, etc.).

Structured output uses **forced tool-use** (Anthropic's `tool_choice`),
not "respond in JSON" + `json.loads` — the response is validated against
the tool's `input_schema` server-side before it's ever returned, matching
this codebase's existing validate-everything convention. See
`scripts/run_llm_demo.py` for an end-to-end proof of both the
unconfigured (fallback) and configured (real API) paths. Every test in
the suite uses `tests/fixtures/fake_llm_client.py`'s `FakeLLMClient` — no
real network call happens anywhere in `pytest`.

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

### Phase 5 — platform
- **Plugins** (`plugins/`): `PluginRegistry` is the single choke point
  where a plugin-provided `Tool`'s `risk_level` is actually enforced
  before it reaches the real `ToolRegistry`. `Orchestrator.run_task` gates
  purely on `tool.risk_level == HIGH_IRREVERSIBLE` with zero knowledge of
  a tool's origin, so a plugin tool is indistinguishable at the approval
  gate from a built-in one — zero orchestrator changes needed.
  `plugins/loader.py::load_plugins` scans two local-only, explicit-opt-in
  sources (a `plugins/` directory, or installed-package entry points under
  group `megachud.plugins`); one plugin's failure never blocks another's
  load or the app's startup, and every attempt is a structured `Event`.
- **Multi-agent readiness** (`models/agent.py`): structural only — a
  minimal `Agent` model (no auth, no process-affinity), with nullable
  `agent_id`/`project_name` columns on `Task`/`Strategy`/`MemoryEntry`/
  `Review`. Still exactly one orchestrator process; this just gives rows a
  stable identity to be tagged with and filtered by, mirroring how
  `Tool.risk_level` existed for two phases before any `HIGH_IRREVERSIBLE`
  tool did. `db.py::ensure_agent_project_columns` is a small, idempotent
  additive `ALTER TABLE` migration — `Base.metadata.create_all()` only
  creates new tables, it never adds columns to tables that already exist,
  and this project's dev DB already had populated tables from Phases 1-4.
- **Event bus swap-point** (`events/bus.py`): `EventBusProtocol` formalizes
  the interface `EventBus`'s own docstring already committed to since
  Phase 1 (in-process, stable interface for a future broker) — a
  `Protocol` since `EventBus` is a concrete class, not a subclass
  hierarchy waiting to be created.
- **Analytics agent filtering** is precisely scoped, not blanket: only
  `task_counts_by_status`/`strategy_success_rates` have a direct
  `agent_id` column and are filtered; tool/event/cost-derived stats are
  read straight from `Event` rows with no join to `Task`, and `Event`
  isn't one of the four tagged tables, so they stay honestly unfiltered.

### LLM Integration
- **`LLMClient`** (`llm/client.py`): the 4th ABC swap-point.
  `AnthropicLLMClient` maps SDK exceptions to `LLMRequestError(retryable=
  ...)` (`APIConnectionError`/`RateLimitError` → retryable,
  `APIStatusError` → retryable only if `status_code >= 500`) so no
  `anthropic.*` exception type ever leaks past this module. Every
  consumer and every test depends only on `megachud.llm.client`, never
  the `anthropic` package directly — `tests/fixtures/fake_llm_client.py`
  is the double used everywhere else in the suite.
- **`.env` loading** (`config.py::_load_dotenv`): a pure function around
  `dotenv_values()` (never `load_dotenv()`, which mutates `os.environ`
  globally) — zero side effects, so tests can point it at an arbitrary
  `tmp_path` file with no cross-test leakage. Precedence (`os.environ`
  wins over `.env`) is resolved once, at the `Settings.load()` call site.
  `anthropic_api_key` is a `pydantic.SecretStr`.
- **`app.py` wiring**: every LLM component is constructed conditionally
  on `settings.anthropic_api_key` being set, and `LLMReflectionGenerator`
  only fills `reflection_generator` if a plugin hasn't already claimed
  that swap-point — so plugin-provided reflection generators still win.
  A single dispatch-free `EventLogger` (no `on_event`) is shared by both
  plugin-load events and `llm_call` cost events, since neither should
  trigger the reflection/curiosity/strategy pipeline.

### Dashboard
- **`api/`, `web/static/`**: FastAPI + plain HTML/JS, no build step.
  Panels: New Task, Working Summary, Pending Approvals, Live Activity,
  Task History (with an agent filter), Memory Browser, Strategy/Workflow
  Browser, Experiment Browser (with inline Promotion approvals),
  Curiosity, Bottleneck Findings, Analytics (with an agent filter),
  Reviews, Model Routing, Plugins. A project/agent identity label sits in
  the header.

Persistence, config, and safety-guardrail details are documented inline
in `src/megachud/config.py`, `src/megachud/db.py`, and
`src/megachud/tools/shell_tool.py`.
