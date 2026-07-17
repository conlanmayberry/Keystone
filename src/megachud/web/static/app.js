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
  const agentId = el("tasks-agent-filter").value;
  const params = new URLSearchParams();
  if (agentId) params.set("agent_id", agentId);
  const tasks = await fetchJson(`/tasks?${params.toString()}`);
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

// --- Analytics ---

function renderAnalytics(report) {
  const banner = el("analytics-cost-banner");
  banner.innerHTML = report.cost_data_available
    ? `<div class="cost-banner success">Total cost: $${report.total_cost_usd.toFixed(4)} (in=${report.total_tokens_input} out=${report.total_tokens_output} tokens)</div>`
    : `<div class="cost-banner">No cost data yet — no LLM calls have been made in this codebase.</div>`;

  const statusRows = Object.entries(report.task_counts_by_status)
    .map(([k, v]) => `<tr><td>${k}</td><td>${v}</td></tr>`)
    .join("") || `<tr><td colspan="2">none</td></tr>`;
  const toolRows = Object.entries(report.tool_call_counts)
    .map(([tool, count]) => `<tr><td>${tool}</td><td>${count}</td><td>${((report.tool_failure_rates[tool] ?? 0) * 100).toFixed(0)}%</td></tr>`)
    .join("") || `<tr><td colspan="3">none</td></tr>`;
  const strategyRows = Object.entries(report.strategy_success_rates)
    .map(([wf, rate]) => `<tr><td>${wf}</td><td>${(rate * 100).toFixed(0)}%</td></tr>`)
    .join("") || `<tr><td colspan="2">none</td></tr>`;

  el("analytics-results").innerHTML = `
    <table class="metric-table"><thead><tr><th>Task status</th><th>Count</th></tr></thead><tbody>${statusRows}</tbody></table>
    <table class="metric-table"><thead><tr><th>Tool</th><th>Calls</th><th>Failure rate</th></tr></thead><tbody>${toolRows}</tbody></table>
    <table class="metric-table"><thead><tr><th>Workflow</th><th>Success rate</th></tr></thead><tbody>${strategyRows}</tbody></table>
    <div class="memory-meta">become_long_term_knowledge_rate: ${(report.become_long_term_knowledge_rate * 100).toFixed(0)}%</div>
  `;
}

async function refreshAnalytics() {
  const windowHours = parseInt(el("analytics-window-hours").value, 10) || 24;
  const agentId = el("analytics-agent-filter").value;
  const params = new URLSearchParams({ window_hours: String(windowHours) });
  if (agentId) params.set("agent_id", agentId);
  const report = await fetchJson(`/analytics?${params.toString()}`);
  renderAnalytics(report);
}

el("analytics-refresh-btn").addEventListener("click", refreshAnalytics);

// --- Reviews ---

function renderReviewReport(report) {
  const costLine = report.costs.cost_data_available
    ? `Total cost: $${report.costs.total_cost_usd.toFixed(4)}`
    : "No cost data yet.";

  let extra = "";
  if (report.kind === "weekly") {
    const evo = (report.workflow_evolution || [])
      .map((w) => `<li>${w.workflow_name}: v${w.active_version ?? "-"} — ${w.version_count} version(s), active success ${w.active_success_rate !== null ? (w.active_success_rate * 100).toFixed(0) + "%" : "n/a"}</li>`)
      .join("");
    const routing = Object.entries(report.model_routing_summary || {}).map(([m, n]) => `<li>${m}: ${n} decision(s)</li>`).join("");
    const recs = (report.recommendations || []).map((r) => `<li>${r}</li>`).join("");
    extra = `
      <h4>Workflow Evolution</h4><ul>${evo || "<li>none</li>"}</ul>
      <h4>Model Routing Summary</h4><ul>${routing || "<li>none</li>"}</ul>
      <h4>Recommendations</h4><ul>${recs || "<li>none</li>"}</ul>
    `;
  }

  el("review-report").innerHTML = `
    <div><strong>${report.kind}</strong> — ${new Date(report.window_start).toLocaleString()} to ${new Date(report.window_end).toLocaleString()}</div>
    <h4>Accomplishments</h4><ul>${report.accomplishments.map((a) => `<li>${a}</li>`).join("") || "<li>none</li>"}</ul>
    <h4>Blockers</h4><ul>${report.blockers.map((b) => `<li>${b}</li>`).join("") || "<li>none</li>"}</ul>
    <h4>Learning</h4><ul>${report.learning.map((l) => `<li>${l}</li>`).join("") || "<li>none</li>"}</ul>
    <div class="memory-meta">${costLine}</div>
    ${extra}
  `;
}

async function previewReview() {
  const kind = el("review-kind-select").value;
  renderReviewReport(await fetchJson(`/reviews/${kind}/preview`));
}

async function generateReview() {
  const kind = el("review-kind-select").value;
  renderReviewReport(await fetchJson(`/reviews/${kind}/generate`, { method: "POST" }));
  refreshReviewHistory();
}

async function refreshReviewHistory() {
  const reviews = await fetchJson("/reviews");
  const container = el("review-history");
  if (reviews.length === 0) {
    container.innerHTML = "No reviews generated yet.";
    return;
  }
  container.innerHTML = "";
  for (const r of reviews) {
    const div = document.createElement("div");
    div.className = "memory-item";
    div.innerHTML = `<div><strong>${r.kind}</strong> — ${new Date(r.created_at).toLocaleString()}</div>`;
    container.appendChild(div);
  }
}

el("review-preview-btn").addEventListener("click", previewReview);
el("review-generate-btn").addEventListener("click", generateReview);

// --- Model Routing ---

async function refreshRoutingProfiles() {
  const profiles = await fetchJson("/routing/profiles");
  const tbody = document.querySelector("#routing-profiles-table tbody");
  if (profiles.length === 0) {
    tbody.innerHTML = `<tr><td colspan="5">No model profiles configured.</td></tr>`;
    return;
  }
  tbody.innerHTML = "";
  for (const p of profiles) {
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>${p.name}</td><td>${p.quality_tier}</td><td>$${p.cost_per_1k_input_tokens}</td><td>$${p.cost_per_1k_output_tokens}</td><td>${p.est_latency_ms}</td>`;
    tbody.appendChild(tr);
  }
}

el("routing-simulate-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const container = el("routing-decision");
  try {
    const decision = await fetchJson("/routing/simulate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_type: el("routing-task-type").value,
        quality_target: parseInt(el("routing-quality-target").value, 10),
        est_tokens_input: parseInt(el("routing-est-input").value, 10) || 0,
        est_tokens_output: parseInt(el("routing-est-output").value, 10) || 0,
      }),
    });
    container.innerHTML = `
      <div class="memory-item">
        <div><strong>Chosen: ${decision.chosen_model}</strong> — est. cost $${decision.estimated_cost_usd.toFixed(6)}</div>
        <div class="memory-meta">${decision.reason}</div>
        <div class="memory-meta">Candidates: ${decision.candidates_considered.join(", ")}</div>
      </div>
    `;
  } catch (err) {
    container.innerHTML = `<div class="memory-meta" style="color: var(--danger)">Error: ${err.message}</div>`;
  }
});

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

// --- Plugins ---

async function refreshPlugins() {
  const results = await fetchJson("/plugins");
  const tbody = document.querySelector("#plugins-table tbody");
  if (results.length === 0) {
    tbody.innerHTML = `<tr><td colspan="4">No plugins configured.</td></tr>`;
    return;
  }
  tbody.innerHTML = "";
  for (const r of results) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${r.name}</td>
      <td>${r.source}</td>
      <td class="status-${r.success ? "succeeded" : "failed"}">${r.success ? "loaded" : "failed"}</td>
      <td>${r.error ?? ""}</td>
    `;
    tbody.appendChild(tr);
  }
}

// --- Meta / identity header + agent filters ---

async function refreshMeta() {
  const meta = await fetchJson("/meta");
  el("identity-label").textContent = `project: ${meta.project_name} · agent: ${meta.agent_name}`;
}

async function populateAgentFilters() {
  const agents = await fetchJson("/agents");
  for (const selectId of ["tasks-agent-filter", "analytics-agent-filter"]) {
    const select = el(selectId);
    const current = select.value;
    select.innerHTML = `<option value="">All agents</option>`;
    for (const a of agents) {
      const option = document.createElement("option");
      option.value = a.id;
      option.textContent = a.name;
      select.appendChild(option);
    }
    select.value = current;
  }
}

el("tasks-agent-filter").addEventListener("change", refreshTasks);
el("analytics-agent-filter").addEventListener("change", refreshAnalytics);

connectLiveFeed();
refreshTasks();
refreshApprovals();
refreshMemory();
refreshStrategies();
refreshExperiments();
refreshCuriosity();
refreshBottlenecks();
refreshAnalytics();
refreshReviewHistory();
refreshRoutingProfiles();
refreshPlugins();
refreshMeta();
populateAgentFilters().then(() => {
  // Re-apply once agent options exist, in case a filter was mid-selection.
  refreshTasks();
  refreshAnalytics();
});
setInterval(refreshTasks, 5000);
setInterval(refreshApprovals, 3000);
setInterval(refreshStrategies, 5000);
setInterval(refreshExperiments, 5000);
setInterval(refreshCuriosity, 3000);
setInterval(refreshAnalytics, 15000);
