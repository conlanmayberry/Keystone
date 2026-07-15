let selectedTaskId = null;

function el(id) {
  return document.getElementById(id);
}

async function fetchJson(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) {
    const body = await response.text();
    throw new Error(`${response.status}: ${body}`);
  }
  return response.json();
}

function appendActivityEvent(event) {
  const feed = el("activity-feed");
  const div = document.createElement("div");
  div.className = "event";
  const ts = event.timestamp ? new Date(event.timestamp).toLocaleTimeString() : "";
  div.innerHTML = `<span class="type">[${event.event_type}]</span> ${ts} task=${event.task_id ?? "-"} tool=${event.tool_name ?? "-"}`;
  feed.prepend(div);
  while (feed.childElementCount > 200) {
    feed.removeChild(feed.lastChild);
  }
}

function connectLiveFeed() {
  const proto = window.location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${window.location.host}/ws/live`);
  ws.onmessage = (msg) => {
    const event = JSON.parse(msg.data);
    appendActivityEvent(event);
    if (["task_completed", "task_failed", "approval_requested", "approval_resolved"].includes(event.event_type)) {
      refreshTasks();
      refreshApprovals();
    }
  };
  ws.onclose = () => setTimeout(connectLiveFeed, 2000);
}

async function refreshTasks() {
  const tasks = await fetchJson("/tasks");
  const tbody = document.querySelector("#tasks-table tbody");
  tbody.innerHTML = "";
  for (const task of tasks) {
    const tr = document.createElement("tr");
    tr.style.cursor = "pointer";
    tr.innerHTML = `
      <td>${task.title}</td>
      <td class="status-${task.status}">${task.status}</td>
      <td>${new Date(task.created_at).toLocaleString()}</td>
      <td>${task.completed_at ? new Date(task.completed_at).toLocaleString() : ""}</td>
    `;
    tr.addEventListener("click", () => selectTask(task.id));
    tbody.appendChild(tr);
  }
}

async function selectTask(taskId) {
  selectedTaskId = taskId;
  const summary = await fetchJson(`/tasks/${taskId}/working_summary`);
  const container = el("working-summary");
  container.innerHTML = `
    <dl>
      <dt>Objective</dt><dd>${summary.objective}</dd>
      <dt>Plan</dt><dd>${summary.plan.length ? summary.plan.join("<br/>") : "(empty)"}</dd>
      <dt>Blockers</dt><dd>${summary.blockers.length ? summary.blockers.join(", ") : "none"}</dd>
      <dt>Next step</dt><dd>${summary.next_step ?? "(finished)"}</dd>
      <dt>Rationale</dt><dd>${summary.rationale}</dd>
    </dl>
  `;
}

async function refreshApprovals() {
  const approvals = await fetchJson("/approvals?status=pending");
  const container = el("approvals-list");
  if (approvals.length === 0) {
    container.innerHTML = "No pending approvals.";
    return;
  }
  container.innerHTML = "";
  for (const approval of approvals) {
    const div = document.createElement("div");
    div.className = "approval-item";
    div.innerHTML = `
      <span>${approval.tool_name} (${approval.risk_level}) — task ${approval.task_id.slice(0, 8)}</span>
      <span class="actions">
        <button class="approve">Approve</button>
        <button class="deny">Deny</button>
      </span>
    `;
    div.querySelector(".approve").addEventListener("click", () => decideApproval(approval.id, true));
    div.querySelector(".deny").addEventListener("click", () => decideApproval(approval.id, false));
    container.appendChild(div);
  }
}

async function decideApproval(approvalId, approved) {
  await fetchJson(`/approvals/${approvalId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  refreshApprovals();
  refreshTasks();
}

el("new-task-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = el("new-task-status");
  try {
    const toolCalls = JSON.parse(el("task-tool-calls").value || "[]");
    const result = await fetchJson("/tasks", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: el("task-title").value,
        prompt: el("task-prompt").value,
        tool_calls: toolCalls,
      }),
    });
    status.textContent = `Task ${result.id} started (${result.status})`;
    status.style.color = "var(--success)";
    refreshTasks();
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.style.color = "var(--danger)";
  }
});

connectLiveFeed();
refreshTasks();
refreshApprovals();
setInterval(refreshTasks, 5000);
setInterval(refreshApprovals, 3000);
