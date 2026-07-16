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
      refreshStrategies();
    }
    if (["promotion_requested", "promotion_resolved"].includes(event.event_type)) {
      refreshExperiments();
      refreshStrategies();
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

function renderMemoryResults(items) {
  const container = el("memory-results");
  if (items.length === 0) {
    container.innerHTML = "No memory entries found.";
    return;
  }
  container.innerHTML = "";
  for (const item of items) {
    const entry = item.entry ?? item;
    const div = document.createElement("div");
    div.className = "memory-item";
    const scoreLabel = item.score !== undefined ? ` — score ${item.score.toFixed(3)}` : "";
    div.innerHTML = `
      <div class="memory-title">${entry.title} <span class="memory-meta">(${entry.memory_type}${scoreLabel})</span></div>
      <div class="memory-meta">${new Date(entry.created_at).toLocaleString()} · tags: ${entry.tags.join(", ") || "none"}</div>
      <div class="memory-content">${entry.content}</div>
    `;
    container.appendChild(div);
  }
}

async function refreshMemory() {
  const type = el("memory-type-filter").value;
  const params = new URLSearchParams();
  if (type) params.set("type", type);
  const items = await fetchJson(`/memory?${params.toString()}`);
  renderMemoryResults(items);
}

async function searchMemory() {
  const q = el("memory-search-box").value.trim();
  if (!q) {
    refreshMemory();
    return;
  }
  const type = el("memory-type-filter").value;
  const params = new URLSearchParams({ q, top_k: "5" });
  if (type) params.set("type", type);
  const results = await fetchJson(`/memory/search?${params.toString()}`);
  renderMemoryResults(results);
}

async function submitUserMemory(e) {
  e.preventDefault();
  const status = el("memory-status");
  try {
    const tags = el("memory-tags").value
      .split(",")
      .map((t) => t.trim())
      .filter(Boolean);
    await fetchJson("/memory/user", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        title: el("memory-title").value,
        content: el("memory-content").value,
        tags,
      }),
    });
    status.textContent = "Remembered.";
    status.style.color = "var(--success)";
    el("new-memory-form").reset();
    refreshMemory();
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.style.color = "var(--danger)";
  }
}

async function reindexVault() {
  const status = el("memory-status");
  const report = await fetchJson("/memory/reindex", { method: "POST" });
  status.textContent = `Reindexed: created=${report.created} updated=${report.updated} skipped=${report.skipped}`;
  status.style.color = report.errors.length ? "var(--danger)" : "var(--success)";
  refreshMemory();
}

el("memory-search-btn").addEventListener("click", searchMemory);
el("memory-list-btn").addEventListener("click", refreshMemory);
el("memory-reindex-btn").addEventListener("click", reindexVault);
el("new-memory-form").addEventListener("submit", submitUserMemory);

// --- Strategy / Workflow Browser ---

async function refreshStrategies() {
  const strategies = await fetchJson("/strategies");
  const byWorkflow = {};
  for (const s of strategies) {
    (byWorkflow[s.workflow_name] ??= []).push(s);
  }

  const container = el("strategy-list");
  if (strategies.length === 0) {
    container.innerHTML = "No strategies yet.";
    return;
  }
  container.innerHTML = "";
  for (const [workflowName, group] of Object.entries(byWorkflow)) {
    const div = document.createElement("div");
    div.className = "strategy-group";
    div.innerHTML = `<div class="strategy-workflow-name">${workflowName}</div>`;
    for (const s of group) {
      const row = document.createElement("div");
      row.className = "strategy-item";
      row.innerHTML = `
        <span class="${s.is_active ? "status-succeeded" : ""}">
          v${s.version} ${s.is_active ? "(active)" : ""} — ${s.title}
        </span>
        <span class="memory-meta">
          id=${s.id.slice(0, 8)} success_rate=${(s.success_rate * 100).toFixed(0)}% (n=${s.sample_count})
        </span>
        <span class="actions">
          <button class="use-id" type="button">Use ID</button>
          ${s.is_active ? "" : '<button class="edit" type="button">Edit</button>'}
        </span>
      `;
      row.querySelector(".use-id").addEventListener("click", () => {
        el("invoke-strategy-id").value = s.id;
      });
      const editBtn = row.querySelector(".edit");
      if (editBtn) {
        editBtn.addEventListener("click", () => editStrategy(s));
      }
      div.appendChild(row);
    }
    container.appendChild(div);
  }
}

async function editStrategy(strategy) {
  const newTitle = prompt("New title:", strategy.title);
  if (newTitle === null) return;
  const newTemplate = prompt("New plan_template (JSON array):", JSON.stringify(strategy.plan_template));
  if (newTemplate === null) return;

  const status = el("strategy-status");
  try {
    await fetchJson(`/strategies/${strategy.id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: newTitle, plan_template: JSON.parse(newTemplate) }),
    });
    status.textContent = "Strategy updated.";
    status.style.color = "var(--success)";
    refreshStrategies();
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.style.color = "var(--danger)";
  }
}

el("invoke-strategy-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = el("strategy-status");
  try {
    const params = JSON.parse(el("invoke-strategy-params").value || "{}");
    const result = await fetchJson(`/strategies/${el("invoke-strategy-id").value}/invoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ params }),
    });
    status.textContent = `Invoked -> task ${result.task_id}`;
    status.style.color = "var(--success)";
    refreshTasks();
    setTimeout(refreshStrategies, 1000);
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.style.color = "var(--danger)";
  }
});

// --- Experiment Browser + Promotions ---

async function refreshExperiments() {
  const experiments = await fetchJson("/experiments");
  const container = el("experiment-list");
  if (experiments.length === 0) {
    container.innerHTML = "No experiments yet.";
  } else {
    container.innerHTML = "";
    for (const exp of experiments) {
      const div = document.createElement("div");
      div.className = "experiment-item";
      const rec = exp.recommendation ? ` — ${exp.recommendation}` : "";
      div.innerHTML = `
        <div><strong>${exp.workflow_name}</strong> <span class="status-${exp.status === "concluded" ? "succeeded" : "running"}">${exp.status}${rec}</span></div>
        <div class="memory-meta">${exp.hypothesis}</div>
        <div class="memory-meta">control=${exp.control_strategy_id.slice(0, 8)} variant=${exp.variant_strategy_id.slice(0, 8)} min_n=${exp.minimum_sample_size}</div>
        <button class="evaluate" type="button">Evaluate now</button>
      `;
      div.querySelector(".evaluate").addEventListener("click", async () => {
        await fetchJson(`/experiments/${exp.id}/evaluate`, { method: "POST" });
        refreshExperiments();
      });
      container.appendChild(div);
    }
  }

  const promotions = await fetchJson("/promotions?status=pending");
  const promoContainer = el("promotion-list");
  if (promotions.length === 0) {
    promoContainer.innerHTML = "No pending promotions.";
    return;
  }
  promoContainer.innerHTML = "";
  for (const p of promotions) {
    const div = document.createElement("div");
    div.className = "approval-item";
    div.innerHTML = `
      <span>${p.workflow_name}: ${p.from_strategy_id.slice(0, 8)} -> ${p.to_strategy_id.slice(0, 8)} (${p.justification})</span>
      <span class="actions">
        <button class="approve">Approve</button>
        <button class="deny">Deny</button>
      </span>
    `;
    div.querySelector(".approve").addEventListener("click", () => decidePromotion(p.id, true));
    div.querySelector(".deny").addEventListener("click", () => decidePromotion(p.id, false));
    promoContainer.appendChild(div);
  }
}

async function decidePromotion(promotionId, approved) {
  await fetchJson(`/promotions/${promotionId}/decision`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ approved }),
  });
  refreshExperiments();
  refreshStrategies();
}

el("new-experiment-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const status = el("experiment-status");
  try {
    await fetchJson("/experiments", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        workflow_name: el("experiment-workflow-name").value,
        hypothesis: el("experiment-hypothesis").value,
        control_strategy_id: el("experiment-control-id").value,
        variant_strategy_id: el("experiment-variant-id").value,
        minimum_sample_size: parseInt(el("experiment-min-samples").value, 10) || 10,
      }),
    });
    status.textContent = "Experiment created.";
    status.style.color = "var(--success)";
    el("new-experiment-form").reset();
    el("experiment-min-samples").value = 10;
    refreshExperiments();
  } catch (err) {
    status.textContent = `Error: ${err.message}`;
    status.style.color = "var(--danger)";
  }
});

// --- Curiosity ---

async function refreshCuriosity() {
  const questions = await fetchJson("/questions?status=pending");
  const qContainer = el("question-list");
  if (questions.length === 0) {
    qContainer.innerHTML = "No pending questions.";
  } else {
    qContainer.innerHTML = "";
    for (const q of questions) {
      const div = document.createElement("div");
      div.className = "memory-item";
      div.innerHTML = `
        <div>${q.question}</div>
        <div class="memory-meta">${q.context}</div>
        <textarea class="answer-box" rows="2" placeholder="Your answer..."></textarea>
        <button class="answer-btn" type="button">Answer</button>
      `;
      div.querySelector(".answer-btn").addEventListener("click", async () => {
        const answer = div.querySelector(".answer-box").value.trim();
        if (!answer) return;
        await fetchJson(`/questions/${q.id}/answer`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ answer }),
        });
        refreshCuriosity();
        refreshMemory();
      });
      qContainer.appendChild(div);
    }
  }

  const objectives = await fetchJson("/research_objectives");
  const oContainer = el("objective-list");
  if (objectives.length === 0) {
    oContainer.innerHTML = "None yet.";
    return;
  }
  oContainer.innerHTML = "";
  for (const o of objectives) {
    const div = document.createElement("div");
    div.className = "memory-item";
    const findings = o.findings.map((f) => `${f.title} (${f.score.toFixed(2)})`).join(", ") || "no findings";
    div.innerHTML = `
      <div><strong>${o.objective_type}</strong> — ${o.description}</div>
      <div class="memory-meta">${findings}</div>
    `;
    oContainer.appendChild(div);
  }
}

// --- Bottleneck Findings ---

async function refreshBottlenecks() {
  const findings = await fetchJson("/bottlenecks");
  const container = el("bottleneck-list");
  if (findings.length === 0) {
    container.innerHTML = "No bottlenecks found.";
    return;
  }
  container.innerHTML = "";
  for (const f of findings) {
    const div = document.createElement("div");
    div.className = "memory-item";
    const proposeBtn = f.kind === "strategy_declining_success" ? '<button class="propose" type="button">Propose Experiment</button>' : "";
    div.innerHTML = `
      <div><strong>[${f.severity.toFixed(2)}] ${f.kind}</strong> / ${f.subject}</div>
      <div class="memory-meta">${f.detail}</div>
      ${proposeBtn}
    `;
    const btn = div.querySelector(".propose");
    if (btn) {
      btn.addEventListener("click", async () => {
        const result = await fetchJson("/bottlenecks/propose_experiment", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(f),
        });
        alert(result.experiment_id ? `Created experiment ${result.experiment_id}` : "No experiment created (already running or no active strategy).");
        refreshExperiments();
        refreshStrategies();
      });
    }
    container.appendChild(div);
  }
}

el("bottleneck-scan-btn").addEventListener("click", refreshBottlenecks);

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
refreshMemory();
refreshStrategies();
refreshExperiments();
refreshCuriosity();
refreshBottlenecks();
setInterval(refreshTasks, 5000);
setInterval(refreshApprovals, 3000);
setInterval(refreshStrategies, 5000);
setInterval(refreshExperiments, 5000);
setInterval(refreshCuriosity, 3000);
