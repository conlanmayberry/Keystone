# MegaChud Plugins

Dynamic plugin loading is local-machine-only and explicit-opt-in: nothing
loads unless you name it in config.

## Local directory plugins

Drop a `.py` file in this directory (e.g. `my_plugin.py`) exposing a
module-level `register(registry) -> None` function. Then add its
filename (without `.py`) to `plugins.enabled_local` in
`config/local.yaml`:

```yaml
plugins:
  enabled_local: ["my_plugin"]
```

## Installed-package plugins

A pip-installed package can declare an entry point under the
`megachud.plugins` group in its own `pyproject.toml`:

```toml
[project.entry-points."megachud.plugins"]
my_plugin = "my_package.plugin_module:register"
```

Then add its entry point name to `plugins.enabled_packages` in
`config/local.yaml`. MegaChud never installs packages itself — installing
the package is a manual `pip install` step you run yourself; MegaChud
never touches PyPI or fetches a URL at runtime.

## What a plugin can register

```python
from megachud.plugins import RiskLevel, Tool, ToolResult

def register(registry):
    registry.register_tool(MyTool())                                # a new Tool
    registry.register_reflection_generator("my_gen", MyGenerator())  # candidate, not auto-active
    registry.register_model_router("my_router", MyRouter())          # candidate, not auto-active
```

A registered `ReflectionGenerator`/`ModelRouter` only becomes *active* if
its name also appears in `plugins.active_reflection_generator`/
`active_model_router` in config — registering alone doesn't make it live.
This is deliberate: the user's config decides what's active, not the
plugin just by loading.

## Safety — read this before writing or enabling a plugin

Python has no in-process sandbox. A loaded plugin runs with the full
privileges of the MegaChud process, exactly like any Python `import`
statement always has. The actual safety mechanisms here are:

1. **Allow-list gating** — nothing loads unless explicitly named in
   config. No auto-discovery, no auto-load-everything-found.
2. **Full observability** — every load attempt is logged as a structured
   `Event` (`plugin_load_succeeded` / `plugin_load_failed`), visible in
   the dashboard's Live Activity feed and the Plugins panel.
3. **`Tool.risk_level` + the approval gate remain the real boundary for
   actions** — a plugin-registered `Tool` is validated to declare a
   `risk_level` before it's added to the tool set, and any
   `high_irreversible` tool call — plugin-provided or built-in — is
   blocked on human approval by `ApprovalGate` before it runs. Once
   registered, a plugin tool is indistinguishable at that gate from a
   built-in one.
4. **`workspace/sandbox.py`'s path confinement is a convention** built-in
   tools use voluntarily, not an OS-level jail — a plugin's own
   `Tool.run()` could in principle ignore it and touch the filesystem
   directly. This is the same trust boundary a hand-written tool always
   had, not a regression plugins introduce.
5. A plugin **cannot silently shadow a built-in tool name** — the real
   `ToolRegistry` raises on duplicate names.

Only enable plugins you wrote yourself or fully trust.

## Example

See `example_uppercase.py` in this directory — a trivial, harmless
`LOW`-risk tool that uppercases text, shipped as a working reference.
