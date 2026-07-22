# MegaChud

Self-improving autonomous AI operating system. This repo implements all
**5 phases** of the roadmap: **Phase 1** (reliable core), **Phase 2**
(memory), **Phase 3** (improvement: strategy/workflow engine, experiments,
curiosity, bottleneck detection), **Phase 4** (optimization: model routing
infrastructure, analytics, hourly/weekly reviews), and **Phase 5**
(platform: dynamic plugin loading, structural multi-agent/multi-project
readiness, advanced dashboards), plus a first real **LLM integration**
(Anthropic Claude), **internet access** (HTTP fetch, file download, web
search), **browser automation** (Playwright — research, monitoring,
testing, approval-gated form interaction), and a **chat interface** with
Auto/Semi-Manual/Full-Manual execution modes layered on top once all 5
phases were done — see "LLM Integration", "Internet Access", "Browser
Automation (Stage B)", and "Chat Interface" below. See the planning docs
for the full picture:

- [Master_Specification.md](Master_Specification.md) — vision, design
  principles, and the full set of components the platform grows into.
- [Implementation_Plan.md](Implementation_Plan.md) — the 5-phase roadmap.
  This repo covers all 5 phases.
- [Engineering_Standards.md](Engineering_Standards.md) — language,
  architecture, logging, and quality standards followed throughout.

Phase 1 deliberately shipped **no internet access and no
transaction/financial tools** — only local, sandboxed file and shell
tools. Every tool declares a `risk_level` (`low` / `medium` /
`high_irreversible`), and any `high_irreversible` tool call is routed
through a human approval gate before it runs. This mechanism was fully
built and tested from day one (see `tests/fixtures/dummy_tools.py`) so
that later phases could add real internet-access and money-related tools
— an explicit acceptance criterion for the finished product — without
reworking the orchestrator. Real internet access has since landed (see
"Internet Access" below): `http_fetch`, `download_file`, and `web_search`
are `LOW`/`MEDIUM` risk and run automatically, same as `read_file`. Real
browser automation has too (see "Browser Automation (Stage B)"): the one
tool that can actually change remote state, `browser_submit`, is
`HIGH_IRREVERSIBLE` and always pauses for human approval — the exact same
gate every risky tool has used since Phase 1, with zero orchestrator
changes needed to add it. Curiosity still searches only existing local
memory, not the new internet/browser tools, and the Model Selection
Engine (`routing/`) is still a config-driven decision framework with no
LLM call inside it anywhere — picking a model is still pure arithmetic,
never itself an LLM call. Four other components (reflection generation,
task planning, curiosity question/objective text, and the chat interface
that proposes plans) have real Anthropic Claude-backed implementations,
gated entirely behind whether `ANTHROPIC_API_KEY` is configured — see
"LLM Integration" and "Chat Interface" below. Phase 5's plugin system was
the first exception to the local-only boundary: dynamic runtime loading
of external Python code is real, deliberately scoped to local-only,
explicit-opt-in sources (see "Plugins" below).

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

```
.venv/Scripts/python scripts/run_internet_demo.py
```

Runs a real 2-step task (`http_fetch` then `download_file` against
`https://example.com/`) through the real orchestrator, prints the
resulting `tool_result` events, then runs a real `web_search` query if
`BRAVE_API_KEY` is configured (otherwise prints the same "not configured"
message style as the LLM demo), and prints the current
`workspace/downloads/` disk usage against its quota. Needs real internet
access to run. See "Internet Access" below for setup.

```
.venv/Scripts/python scripts/run_browser_demo.py
```

Runs a real 2-step task (`browser_navigate` then `browser_read` against
`https://example.com/`) through the real orchestrator in a real headless
Chromium, prints the `tool_result` events, and confirms the browser
session is torn down after the task. Requires `pip install .[browser]` +
`playwright install chromium`; fails gracefully with a clear message if
the browser binary is missing. See "Browser Automation (Stage B)" below.

```
.venv/Scripts/python scripts/run_chat_demo.py
```

Drives the real `/conversations` HTTP API (via FastAPI's `TestClient` —
no server needs to be running; this exercises the exact route code the
dashboard's Chat tab calls) through all three execution modes against a
real Anthropic API call: Auto (plan launches immediately), Semi-Manual
(plan sits pending until `approve_plan` is called once), and Full-Manual
(every individual tool call pauses for approval — this script approves
each one as it appears, same as clicking "Approve" in the dashboard
would). With no `ANTHROPIC_API_KEY` configured, prints a clean message
and stops after showing that conversations can still be created. See
"Chat Interface" below for setup.

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

## Internet Access

The first real internet access in this codebase — three new built-in
`Tool`s (`tools/internet_tools.py`, `tools/web_search_tool.py`):
`http_fetch` (GET a URL, return its text), `download_file` (save a URL's
content under `workspace/downloads/`), and `web_search` (Brave Search
API). `http_fetch` and `download_file` are `LOW`/`MEDIUM` risk and always
registered — no setup needed. `web_search` needs a key (see Setup below)
and is simply absent from the tool registry without one.

**Setup**: only `web_search` needs anything. Add
`BRAVE_API_KEY=your-key` to `.env` (get a key at
[api.search.brave.com](https://api.search.brave.com) — generous free
tier, no OAuth). Follows the exact `ANTHROPIC_API_KEY` pattern:
`pydantic.SecretStr`, loaded only from a real environment variable or
`.env`, never written to `default.yaml`/`local.yaml`.

**The safety model, stated honestly:**
- **SSRF / private-network guard** (`internet/url_safety.py`): every URL
  — the original and every redirect hop — is DNS-resolved and rejected
  if any resolved address is private, loopback, link-local, reserved, or
  multicast (this also catches numeric-IP-literal obfuscation tricks like
  `http://2130706433/`, since resolution normalizes them to a real
  address first). httpx's own `follow_redirects=True` does **not**
  re-validate hops — that's a known SSRF bypass — so both fetch and
  download follow redirects manually, re-checking each one.
- **This is not a phishing or malicious-content detector.** Nothing here
  can tell a legitimate site from a scam lookalike domain — that's a
  fundamentally different, much harder problem this project doesn't
  attempt to solve, and the code says so directly rather than implying
  otherwise.
- **Known, deliberate limitation**: the safety check validates the
  resolved address *before* connecting; a DNS-rebinding attacker could
  change the answer between that check and the actual connection
  (TOCTOU). Closing that fully needs a transport that pins the validated
  IP for the real socket connect — a real, buildable follow-up, not done
  here.
- **Downloads** are capped per-file and by a total-folder quota (streamed
  and enforced live, never trusting a server's `Content-Length` header),
  land in `workspace/downloads/` (browse it directly — nothing new to
  learn, it's the same sandboxed workspace every other tool already
  writes to), reject known executable extensions before writing any bytes
  (`.exe`, `.msi`, `.bat`, `.ps1`, etc. — configurable), sanitize
  filenames against path traversal regardless of source (explicit arg,
  `Content-Disposition` header, or the URL itself), and never silently
  overwrite or evict existing files — a quota breach or name collision
  fails cleanly instead.

All of this is configurable under `internet:` in `config/default.yaml`
(`domain_allowlist`/`domain_denylist` — both empty by default, meaning
any public domain is reachable; per-tool byte/timeout/redirect caps).

These Stage A tools do not drive a real browser and cannot submit forms.
Real browser automation — including the approval-gated form submission
that *can* change remote state — is **Browser Automation (Stage B)**
below, and it uses the exact `RiskLevel.HIGH_IRREVERSIBLE` → `ApprovalGate`
mechanism every `high_irreversible` tool already goes through, per
`Tool`'s own docstring ("needs no orchestrator changes, only a new Tool
subclass and a registry entry").

See `scripts/run_internet_demo.py` for an end-to-end proof against the
real internet. Every test in the suite uses `httpx.MockTransport` plus a
stubbed DNS resolver — no real network call happens anywhere in `pytest`.

## Browser Automation (Stage B)

Real, JS-capable browser control via Playwright, for research (navigate +
read rendered pages), monitoring (watch pages for changes), testing
(drive your own web apps), and **approval-gated** form interaction. Five
tools in `tools/browser_tools.py`, all sharing one browser session per
task:

| tool | risk | approval | what it does |
|------|------|----------|--------------|
| `browser_navigate` | MEDIUM | auto | open a URL (SSRF-checked, runs page JS) |
| `browser_read` | LOW | auto | read the page (text / links / accessibility tree) |
| `browser_fill` | MEDIUM | auto | type into a field (cannot submit on its own) |
| `browser_click` | MEDIUM | auto\* | click a link / plain button |
| `browser_submit` | HIGH_IRREVERSIBLE | **human** | submit a form / state-changing control |

**Setup**: `pip install .[browser]` then the one-time
`playwright install chromium`. With neither present the browser tools
return a clean failure and `create_app()` still boots — nothing else is
affected.

**The click safety model, stated honestly (\*)**: `browser_click`
inspects its target first and **refuses** anything that looks
state-changing — `type=submit`/`image`, a no-explicit-type `<button>`
inside a `<form>`, or visible text matching a configurable
buy/pay/order/delete/send denylist — directing the caller to
`browser_submit` instead. This inspection reads static DOM attributes and
visible text only, so a JS `onclick` handler or a control disguised as a
plain link can still change state without tripping it. **The heuristic is
a guardrail; the approval gate is the real protection.** Anything that
genuinely changes remote state should go through `browser_submit`, which
routes every call through the same human approval gate as any other
`HIGH_IRREVERSIBLE` tool — approve/deny it from the dashboard, exactly
like a risky `shell_exec`.

**One deliberate orchestrator change** (the only one in the project): a
browser session must persist across the `navigate → read → …` steps of a
plan, but tools receive only `args`, never a `task_id`. `run_task` now
sets an ambient `contextvars.ContextVar` (`orchestrator/context.py`) that
session-based tools read; the tool interface `run(args)` is unchanged.
Sessions are one browser+context per task, created lazily and closed when
the task ends by a `BrowserSessionCleanupHandler` wired into the existing
`EventDispatcher` — all within the task's own worker thread, which is what
makes Playwright's thread-affine sync API safe here. **Honest
limitation**: a hard crash mid-task (a tool violating the never-raise
contract — a bug) could leak one browser subprocess until process exit;
mitigated by the never-raise convention, unique task ids, and
`close_all()` on shutdown.

**Explicitly not built, and not planned**: no account creation, no
CAPTCHA/bot-detection solving, and no tooling for covert paid "human"
microwork — that last one is undisclosed AI labor sold to buyers paying
for a human (a ToS violation and a deception), independent of the two
hard-prohibited actions it would also require.

See `scripts/run_browser_demo.py` for a real navigate+read against a live
page. The unit suite uses a fake page double (no real Chromium);
`tests/test_browser_e2e.py` is an opt-in real-browser test, skipped unless
`MEGACHUD_BROWSER_E2E=1` is set.

## Chat Interface

A real multi-turn conversation with the agent — the dashboard's Chat tab,
backed by `ConversationEngine` (`conversation/engine.py`) and
`POST /conversations/{id}/messages`. **The property every prior
capability in this project depends on is unchanged: plan *execution*
stays strictly one-shot.** The LLM proposes one complete plan per turn
and never sees tool results, so it cannot revise a plan mid-execution
based on what happened — multi-turn lives entirely in "how we arrive at
a plan," never in "how the plan runs." Once a plan is approved (or
auto-approved), it runs through the same unmodified `Orchestrator.run_task`
every other task does.

Each turn, the LLM picks one of two actions via forced tool-use: ask a
clarifying question, or propose a finished plan. `history` passed to the
LLM is plain conversation text only — prior message content, never a
tool result or a previously-proposed plan's raw JSON — which is what
structurally prevents it from ever "seeing what happened."

**Three execution modes**, selected per-message from the dashboard's
segmented control (or `execution_mode` on `POST /tasks`):
- **Auto**: the proposed plan launches immediately. `HIGH_IRREVERSIBLE`
  steps (like `browser_submit`) still pause for approval — this mode
  doesn't bypass that gate, it just skips the *extra* whole-plan review.
- **Semi-Manual**: the plan sits `pending` in the chat until you click
  Approve or Reject once; approving launches it to completion exactly
  like Auto from that point on.
- **Full-Manual**: every individual tool call pauses for approval,
  regardless of `risk_level` — reusing the exact same `ApprovalGate` every
  `HIGH_IRREVERSIBLE` tool already uses, just applied to every step. No
  new approval machinery; `Task.execution_mode == "full_manual"` is
  checked once, before the existing `risk_level == HIGH_IRREVERSIBLE`
  check, in `Orchestrator.run_task`.

**Setup**: same `ANTHROPIC_API_KEY` as "LLM Integration" above — nothing
additional. With no key configured, conversations can still be created
(that doesn't need an LLM), but sending a message returns a clean `503`,
demonstrated by `scripts/run_chat_demo.py`.

Anthropic's Messages API requires strict `user`/`assistant` alternation
starting with `user`. `send_message` always writes exactly one `user` row
then exactly one `assistant` row — even when the LLM call itself fails —
so a dangling unanswered turn never breaks the next request.

See `scripts/run_chat_demo.py` for a real end-to-end proof of all three
modes. Every test uses `tests/fixtures/fake_llm_client.py`'s
`FakeLLMClient` — no real network call happens anywhere in `pytest`.

**Draft Prompt**: a "Draft Prompt" button next to Send, backed by
`PromptDrafter` (`conversation/prompt_drafter.py`) and
`POST /prompts/draft`. Type rough, informal notes into the chat box,
click it, and the drafted text *replaces* the box for you to review or
edit — it is **not** a 4th execution mode: it never sends a message or
launches anything, it's a purely optional rewrite step before you pick
Auto/Semi-Manual/Full-Manual and hit Send yourself. It's also the first
plain-text (non-forced-tool-use) LLM call in this codebase — the desired
output is one string, not multiple structured fields, so the forced
tool-use `AnthropicLLMClient` uses everywhere else would be needless
structure here. Uses the cheaper `claude-haiku-4-5-20251001` tier (same
policy as reflection/curiosity — this is a lightweight rewrite, not deep
reasoning) and logs its cost the same way every other LLM consumer does.
Same `ANTHROPIC_API_KEY` setup as the rest of this section; returns a
clean `503` if unconfigured, `502` on a real API request failure.

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

### Internet Access
- **`internet/url_safety.py::check_url_safety`**: the single SSRF/scheme
  gate every URL-based tool calls, on the original URL and on every
  redirect hop. DNS-resolves the hostname (the one seam tests
  monkeypatch — no real DNS lookups anywhere in the suite) and rejects
  the request if *any* resolved address is private/loopback/link-local/
  reserved/multicast, not just the first — a hostname that round-robins
  between a public and a private answer must still fail.
- **`tools/internet_tools.py::open_validated_stream`**: a shared context
  manager both `HttpFetchTool` and `DownloadFileTool` build on — a
  manual, bounded redirect loop (`httpx.Client(follow_redirects=False)`)
  that re-runs `check_url_safety` before connecting to each hop, since
  httpx's own auto-follow-redirects does not re-validate hops (a known
  SSRF bypass). Both tools read the response body via a capped streaming
  loop rather than trusting `Content-Length`.
- **`DownloadFileTool`**: `MEDIUM` risk (writes to disk, same tier as
  `write_file`) vs. `HttpFetchTool`/`WebSearchTool`'s `LOW` (read-only) —
  the same risk-tiering logic `ShellExecTool`/`WriteFileTool` already
  established, not a new policy. Filename sanitization happens before
  `resolve_safe_path` is ever called, since `workspace/sandbox.py` only
  confines paths, it has no filename sanitizer of its own. The
  folder-quota check runs *after* a file is written (summing actual
  on-disk usage, including the just-written file, in one directory scan)
  rather than trying to pre-compute available space — simpler, and still
  never evicts an existing file to make room.
- **`WebSearchTool`**: intentionally a bare class, not a provider-ABC —
  this codebase only introduces an abstraction (like `LLMClient`) when
  there are two real implementations from day one; here there's exactly
  one (Brave), so a bare class is the honest amount of structure.
- **`app.py` wiring**: `http_fetch`/`download_file` are unconditional,
  same tier as `read_file`/`write_file`/`shell_exec`. `web_search` follows
  the exact `settings.anthropic_api_key` conditional-registration pattern
  — only registered when `settings.brave_api_key` is set, so a fresh
  clone with no search key still boots identically (verified by test,
  mirroring `test_create_app_does_not_raise_with_no_api_key`).

### Browser Automation (Stage B)
- **Session keying** (`orchestrator/context.py`): the project's one
  deliberate orchestrator change — a `contextvars.ContextVar` set at the
  top of `run_task` and reset in a `finally`. It exists solely so
  session-based tools can associate a persistent browser with the running
  task without changing the stateless `run(args)` tool interface. Every
  other tool ignores it.
- **`BrowserSessionManager`** (`browser/session.py`): one browser +
  context + page per `task_id`, lazily launched (playwright imported
  locally, mirroring `AnthropicLLMClient`'s `import anthropic`, so the
  base install and `create_app` are unaffected without it). A
  `page_factory` seam lets tests inject a fake page — the browser analogue
  of `httpx.MockTransport`/`FakeLLMClient`, so no real Chromium runs in
  `pytest`.
- **Thread-affinity is the crux**: Playwright's sync API is thread-bound.
  Tasks run in `ThreadPoolExecutor` worker threads with no asyncio loop,
  start-to-finish in one thread; the browser is created, driven, and
  closed entirely within that thread — including
  `BrowserSessionCleanupHandler`, which fires inside `event_logger.log()`
  on `task_completed`/`task_failed` (same thread) and is wired **last** in
  the `EventDispatcher` so nothing reads task state after teardown.
- **`browser_click`'s heuristic** (`_is_state_changing`) inspects static
  DOM + visible text to refuse submit-like clicks, deferring them to the
  approval-gated `browser_submit`. Documented as best-effort, not a
  guarantee — the `HIGH_IRREVERSIBLE` approval gate is the real
  protection, reused verbatim from Phase 1 with zero new approval code.

### Chat Interface
- **`Conversation`/`ConversationMessage`** (`models/conversation.py`):
  brand-new tables, no migration needed. `execution_mode` also lives on
  `ConversationMessage` (not just the eventual `Task`), since for
  Semi-Manual, `approve_plan` happens in a later, separate request — the
  route needs to remember which mode governed that turn.
- **`orchestrator/plan_validation.py`**: the tool-name/args validation
  loop extracted out of `LLMTaskPlanner.plan()` so `ConversationEngine`
  calls the exact same validation, not a re-implementation — a
  hallucinated tool name or invalid args is rejected identically whether
  it came from `POST /tasks {"auto_plan": true}` or a chat message.
- **`Task.execution_mode`** (nullable, additive migration in `db.py`
  mirroring `ensure_agent_project_columns`'s shape): `NULL` and `"auto"`
  are treated identically at read time, so every pre-existing row stays
  correct with no backfill.
- **`ConversationEngine.respond()`**: one forced-tool-use call per
  invocation — multi-turn is entirely a property of the caller (the API
  route) invoking this repeatedly, once per human message. The class
  itself has no notion of a running task and never sees tool results.
- **`routes_conversations.py`**: `send_message` always persists exactly
  one user row and exactly one assistant row before returning, even on
  an LLM failure — required for the next turn's history to satisfy
  Anthropic's strict alternation rule. Task launches go through
  `app.state.executor.submit(...)`, the same background-thread pattern
  `POST /tasks` already used, so a chat message never blocks on task
  execution.

### Dashboard
- **`api/`, `web/static/`**: FastAPI + plain HTML/JS, no build step,
  reorganized into tabs (Chat, Run, Tasks, Memory, Improve, Insights) as
  the panel count grew past what a single scrolling page could hold
  comfortably. Chat is the landing tab: conversation list, message
  thread, and the Auto/Semi-Manual/Full-Manual selector. Run holds New
  Task (with both the `auto_plan` and `execution_mode` controls),
  Working Summary, Pending Approvals, and Live Activity — the
  moment-to-moment "what's happening right now" view. Tasks, Memory,
  Improve (Strategies/Bottlenecks/Experiments/Promotions), and Insights
  (Analytics/Reviews/Model Routing/Plugins) hold everything else. A
  project/agent identity label sits in the header; the active tab
  persists in `localStorage`.

Persistence, config, and safety-guardrail details are documented inline
in `src/megachud/config.py`, `src/megachud/db.py`, and
`src/megachud/tools/shell_tool.py`.
