from __future__ import annotations

import contextvars

# Ambient id of the task currently executing in this thread's context.
#
# Tools receive only `args` from Orchestrator.run_task — never a task_id.
# That's fine for stateless tools (file/shell/http), but session-based
# tools (the browser tools) need to associate a persistent resource — a
# live browser — with the running task across several tool calls in one
# plan. Orchestrator.run_task sets this at the top and resets it in a
# `finally`; a session-based tool reads it via current_task_id.get().
#
# A ContextVar (not a module global or a threading.local) is the right
# primitive: it's the standard "ambient context for the current logical
# operation," it's set and read within the same worker thread the task
# runs in, and reset() restores cleanly even if the task raises.
current_task_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_task_id", default=None)
