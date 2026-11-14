"use strict";

const $ = (id) => document.getElementById(id);
const state = { reports: [], tab: "pipeline", cursor: null, issue: null, reportLoad: 0, queueLoad: 0 };
const pipelineSteps = {
  read: "Read input files", stage: "Extract and stage rows", validate: "Validate and normalize",
  match: "Exact and fuzzy matching", publish: "Publish reports", evaluate: "Evaluate results",
};
const categories = {
  missing_settlement: "Missing settlement", duplicate_settlement: "Duplicate settlement",
  amount_mismatch: "Amount mismatch", late_settlement: "Late settlement",
  reference_mismatch: "Reference mismatch", ambiguous_match: "Ambiguous match",
  unexpected_settlement: "Unexpected settlement", data_quality: "Data quality",
};
const exposure = {
  outstanding_expected: "Outstanding collections", unexplained_amount_discrepancy: "Amount discrepancies",
  duplicate_exposure: "Duplicate exposure", late_settled_value: "Late-settled value",
  unresolved_review_exposure: "Awaiting match review",
};
const actionLabels = {
  detected: "Detected", cleared: "Cleared", reactivated: "Reactivated",
  updated: "Evidence updated", resolve: "Resolved", reopen: "Reopened",
};
const reasonLabels = {
  below_score_or_reciprocal_margin: "The reference score or the lead over a competing candidate was too low.",
  competing_exact_claims: "More than one candidate or claimant had the same exact evidence.",
  competing_diagnostic_claims: "Multiple candidates shared the exact reference.",
  unique_exact_or_observed_original: "The exact match was unique or had the earliest observed arrival.",
  unique_exact_reference_with_unequal_amount: "The exact reference was unique and the amounts differed.",
  reciprocal_top_score_and_margin: "Both records preferred this link by the required margin.",
};
const integer = new Intl.NumberFormat("en-IN");
const percent = new Intl.NumberFormat("en-IN", { style: "percent", maximumFractionDigits: 2 });
const money = (value) => {
  if (value == null) return "—";
  const n = BigInt(value);
  const magnitude = n < 0n ? -n : n;
  return (n < 0n ? "−" : "") + "₹" + integer.format(magnitude / 100n) + "." + String(magnitude % 100n).padStart(2, "0");
};
const dateLabel = (value) => new Intl.DateTimeFormat("en-IN", {
  year: "numeric", month: "long", day: "numeric", timeZone: "UTC",
}).format(new Date(value + "T00:00:00Z"));
const timeLabel = (value) => new Intl.DateTimeFormat("en-IN", {
  dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata",
}).format(new Date(value.replace(" ", "T"))) + " IST";
const title = (key) => key.replaceAll("_", " ").replace(/^./, (letter) => letter.toUpperCase());

function el(tag, value, className) {
  const item = document.createElement(tag);
  if (value != null) item.textContent = value;
  if (className) item.className = className;
  return item;
}

function notice(id, message, success = false) {
  $(id).textContent = message;
  $(id).hidden = !message;
  $(id).classList.toggle("success", success);
}

async function request(path, body) {
  const options = body ? { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body) } : {};
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) {
    const error = new Error(data.error || "The dashboard could not complete the request.");
    if (response.status === 404 && data.error === "Page not found." &&
        (path === "/api/pipeline" || path.endsWith("/reconcile"))) {
      error.message = "This dashboard server needs a restart. Stop it in the terminal, then run .\\dashboard.cmd again.";
    }
    error.status = response.status;
    throw error;
  }
  return data;
}

function selectOptions(select, choices, selected) {
  select.replaceChildren(...choices.map(([key, label]) => new Option(label, key)));
  if (choices.some(([key]) => String(key) === String(selected))) select.value = selected;
}

function connection(label, connected) {
  $("connection").textContent = label;
  $("connection-dot").classList.toggle("ready", connected);
}

async function refresh(selection) {
  $("refresh").disabled = true;
  notice("notice", "");
  try {
    state.reports = await request("/api/reports");
    connection("Local database connected", true);
    showReportWorkspace();
    $("empty").textContent = "No published reports. Generate a dataset and run reconciliation to see results here.";
    if (!state.reports.length) return;
    const scopes = [...new Set(state.reports.map((report) => report.scope))];
    scopes.sort((a, b) => (a === "evaluation" ? -1 : b === "evaluation" ? 1 : a.localeCompare(b)));
    const scopeLabel = (scope) => scope.startsWith("dataset-") ? "Dataset " + scope.slice(8, 16) : scope;
    selectOptions($("scope"), scopes.map((scope) => [scope, scopeLabel(scope)]), selection?.scope || $("scope").value);
    fillDays(selection?.day || $("day").value);
    await loadTab(true);
  } catch (error) {
    connection(error.status === 401 ? "Sign-in needed" : "Disconnected", false);
    notice("notice", error.message);
  } finally {
    $("refresh").disabled = false;
  }
}

function fillDays(prior) {
  const days = state.reports.filter((report) => report.scope === $("scope").value);
  selectOptions($("day"), days.map((report) => [report.business_date, dateLabel(report.business_date)]), prior);
}

const context = () => new URLSearchParams({ scope: $("scope").value, day: $("day").value });

function showReportWorkspace() {
  $("workspace").hidden = state.tab === "pipeline" || !state.reports.length;
  $("empty").hidden = state.tab === "pipeline" || Boolean(state.reports.length);
}

function switchTab(tab, load = true) {
  state.tab = tab;
  $("pipeline-page").hidden = tab !== "pipeline";
  for (const name of ["pipeline", "reports", "issues"]) {
    const active = name === tab;
    if (name !== "pipeline") $(name).hidden = !active;
    $(name + "-tab").classList.toggle("selected", active);
    if (active) $(name + "-tab").setAttribute("aria-current", "page");
    else $(name + "-tab").removeAttribute("aria-current");
  }
  showReportWorkspace();
  if (tab === "pipeline") return;
  $("page-title").textContent = tab === "reports" ? "Daily reports" : "Exceptions";
  $("page-subtitle").textContent = tab === "reports" ? "Reconciliation results by business date." :
    "Inspect candidates and record review decisions.";
  if (load) refresh();
}

async function loadTab(reset) {
  if (state.tab === "pipeline") return;
  if (state.tab === "issues") return loadQueue(false);
  const ticket = ++state.reportLoad;
  const versions = await request("/api/reports?" + context());
  if (ticket !== state.reportLoad) return;
  selectOptions($("snapshot"), versions.map((version) => [version.id,
    (version.current ? "Current · " : "Historical · ") + timeLabel(version.cutoff)]),
  reset ? undefined : $("snapshot").value);
  if (versions.length) await loadReport();
}

function pairs(target, entries, format) {
  $(target).replaceChildren(...entries.map(([label, value]) => {
    const row = el("div");
    row.append(el("dt", label), el("dd", format(value)));
    return row;
  }));
}

async function loadReport() {
  const ticket = ++state.reportLoad;
  const report = await request("/api/reports/" + $("snapshot").value);
  if (ticket !== state.reportLoad) return;
  $("snapshot-label").textContent = report.current ? "Current snapshot" : "Historical snapshot";
  $("report-date").textContent = dateLabel(report.business_date);
  $("report-context").textContent = "Complete · Result #" + report.result_id + " · Run #" + report.run_id;
  $("report-cutoff").textContent = "As of " + timeLabel(report.cutoff);
  const rate = report.ledger_count ? (report.ledger_matched * 100 / report.ledger_count).toFixed(1) : null;
  $("match-donut").style.setProperty("--rate", (rate || "0") + "%");
  $("match-rate").textContent = rate === null ? "—" : rate + "%";
  $("match-summary").textContent = integer.format(report.ledger_matched) + " / " +
    integer.format(report.ledger_count) + " ledger entries";
  $("downloads").replaceChildren(...["json", "csv", "md"].map((format) => {
    const link = el("a", "↓ " + format.toUpperCase(), "button quiet");
    link.href = "/api/reports/" + report.result_id + "." + format;
    return link;
  }));
  $("metrics").replaceChildren(...[
    ["Exact matches", report.exact_matches], ["Fuzzy matches", report.fuzzy_matches],
    ["Amount diagnostics", report.diagnostic_matches], ["Unmatched ledger", report.ledger_unmatched],
  ].map(([label, value]) => {
    const card = el("dl", null, "metric");
    card.append(el("dt", label), el("dd", integer.format(value)));
    return card;
  }));
  const breakdown = Object.entries(report.exception_counts).sort((a, b) => b[1] - a[1]);
  const maximum = Math.max(1, ...breakdown.map((entry) => entry[1]));
  $("breakdown").replaceChildren(...breakdown.map(([key, value]) => {
    const row = el("div", null, "breakdown-row");
    const label = el(report.current ? "button" : "span", categories[key] || title(key));
    if (report.current) {
      label.type = "button";
      label.addEventListener("click", () => {
        $("filters").reset();
        $("category").value = key;
        switchTab("issues");
      });
    }
    const bar = el("progress");
    bar.max = maximum;
    bar.value = value;
    bar.setAttribute("aria-label", label.textContent);
    row.append(label, bar, el("strong", integer.format(value)));
    return row;
  }));
  pairs("exposure", Object.entries(exposure).map(([key, label]) => [label, report.exposure[key]]), money);
  pairs("totals", [["Expected gross", report.expected_gross], ["Settled gross", report.settlement_gross],
    ["Settled net", report.settlement_net], ["Settlement fees", report.settlement_fees]], money);
  $("checks").replaceChildren(...Object.entries(report.conservation).map(([key, ok]) =>
    el("li", (ok ? "Passed · " : "Failed · ") + title(key))));
  $("manifests").replaceChildren(...report.inputs.map((input) => el("li",
    input.source + " · " + input.kind + " · " + input.sha256)));
}

function badge(issue) {
  const text = issue.active ? title(issue.review_status) : "Cleared · " + title(issue.review_status);
  return el("span", text, "badge " + (issue.active ? issue.review_status : "cleared"));
}

async function loadQueue(append) {
  const ticket = ++state.queueLoad;
  const params = context();
  for (const key of ["category", "status", "merchant"]) {
    const value = $(key).value.trim();
    if (value) params.set(key, value);
  }
  if ($("inactive").checked) params.set("include_inactive", "1");
  if (append && state.cursor) params.set("after", state.cursor);
  $("more").disabled = true;
  if (!append) {
    $("issue-rows").replaceChildren();
    $("queue-count").textContent = "Loading cases…";
  }
  try {
    const result = await request("/api/issues?" + params);
    if (ticket !== state.queueLoad) return;
    state.cursor = result.next;
    for (const issue of result.issues) {
      const row = el("tr");
      row.append(el("td", "#" + issue.id), el("td", categories[issue.category] || title(issue.category)),
        el("td", issue.merchant || "—"), el("td", money(issue.amount)));
      const status = el("td");
      status.append(badge(issue));
      const action = el("td");
      const button = el("button", "Review", "button quiet");
      button.type = "button";
      button.setAttribute("aria-label", "Review exception " + issue.id);
      button.addEventListener("click", () => act(() => openIssue(issue.id)));
      action.append(button);
      row.append(status, action);
      $("issue-rows").append(row);
    }
    const count = $("issue-rows").children.length;
    $("queue-count").textContent = count ? integer.format(count) + " cases shown" : "No exceptions match these filters.";
    $("more").hidden = !state.cursor;
  } catch (error) {
    if (ticket === state.queueLoad) $("queue-count").textContent = "Could not load cases.";
    throw error;
  } finally {
    if (ticket === state.queueLoad) $("more").disabled = false;
  }
}

function renderEvidence(issue) {
  const details = issue.evidence;
  const evidence = $("evidence");
  evidence.replaceChildren();
  if (details.reason) evidence.append(el("p", reasonLabels[details.reason] || title(details.reason), "evidence-note"));
  const candidates = details.candidates || [];
  if (candidates.length) {
    const container = el("div", null, "table-wrap evidence-table");
    const table = el("table");
    const heading = table.createTHead().insertRow();
    for (const key of ["Ledger reference", "Settlement reference", "Score", "Difference", "Days"]) {
      heading.append(el("th", key));
    }
    const body = table.createTBody();
    for (const item of candidates) {
      const row = body.insertRow();
      for (const value of [item.ledger_reference, item.settlement_reference, item.score,
        money(item.amount_difference), item.date_difference]) row.append(el("td", value));
    }
    container.append(table);
    evidence.append(container);
  } else {
    const fields = ["ledger", "settlement", "original", "extras", "rejection_code"];
    const values = fields.filter((key) => details[key] != null);
    for (const key of values) evidence.append(el("p", title(key) + " · " + details[key], "evidence-note"));
  }
  $("source-count").textContent = "(" + issue.source_rows.length + ")";
  $("sources").replaceChildren(...issue.source_rows.map((row) => {
    const section = el("section");
    section.append(el("p", row.source + " · " + row.kind + " · row " + row.row_number));
    if (row.rejection_reason) section.append(el("p", row.rejection_reason));
    section.append(el("pre", JSON.stringify(JSON.parse(row.payload), null, 2)));
    return section;
  }));
}

async function openIssue(id, saved = false) {
  const { issue, history } = await request("/api/issues/" + id);
  state.issue = issue;
  $("issue-number").textContent = "CASE #" + issue.id + " · VERSION " + issue.version;
  $("issue-title").textContent = categories[issue.category] || title(issue.category);
  $("issue-summary").replaceChildren(badge(issue), el("span", issue.merchant || "Source validation"),
    el("span", money(issue.amount)), el("span", dateLabel(issue.business_date)));
  renderEvidence(issue);
  $("history").replaceChildren(...history.map((entry) => {
    const item = el("li");
    item.append(el("strong", actionLabels[entry.action]), el("small", " · " + entry.actor + " · " +
      timeLabel(entry.created_at)), el("p", entry.reason));
    return item;
  }));
  $("reason").value = "";
  $("review-submit").textContent = issue.review_status === "open" ? "Resolve exception" : "Reopen exception";
  $("reload-issue").hidden = true;
  notice("issue-notice", saved ? "Review decision saved." : "", saved);
  if (!$("issue-detail").open) $("issue-detail").showModal();
}

async function saveReview(event) {
  event.preventDefault();
  const issue = state.issue;
  const actor = $("actor").value.trim();
  const reason = $("reason").value.trim();
  if (!actor || !reason) return notice("issue-notice", "Enter an operator name and a review reason.");
  $("review-submit").disabled = true;
  try {
    await request("/api/issues/" + issue.id + "/review", {
      actor, reason, version: issue.version, action: issue.review_status === "open" ? "resolve" : "reopen",
    });
  } catch (error) {
    notice("issue-notice", error.message);
    $("reload-issue").hidden = error.status !== 409;
    $("review-submit").disabled = false;
    return;
  }
  try {
    if ($("issue-detail").open) await openIssue(issue.id, true);
    await loadQueue(false);
  } catch (error) {
    notice("issue-notice", "Review saved. Reload to see the latest case.");
    $("reload-issue").hidden = false;
  } finally {
    $("review-submit").disabled = false;
  }
}

async function act(action) {
  notice("notice", "");
  try { await action(); } catch (error) { notice("notice", error.message); }
}

function showDataset(dataset) {
  const changed = state.dataset?.id !== dataset.id;
  state.dataset = dataset;
  if (changed) renderPipeline(null);
  const ledger = dataset.files.find((file) => file.kind === "ledger");
  const settlements = dataset.files.find((file) => file.kind === "settlement");
  $("dataset-summary").textContent = integer.format(ledger.rows) + " ledger rows · " +
    integer.format(settlements.rows) + " settlement rows · seed " + dataset.seed;
  $("dataset-downloads").replaceChildren(...[
    [ledger.name, "Ledger CSV"], [settlements.name, "Settlements CSV"],
    ["manifest.json", "Manifest JSON"], ["answer_key.json", "Answer key JSON"],
  ].map(([name, label]) => {
    const link = el("a", label, "button quiet");
    link.href = "/api/datasets/" + dataset.id + "/" + name;
    return link;
  }));
  $("dataset-downloads").hidden = false;
}

function updateDatasetButtons() {
  $("run-pipeline").hidden = !state.dataset;
  $("run-pipeline").disabled = Boolean(!state.dataset || state.pipelineBusy || state.generating);
  $("generate-dataset").disabled = Boolean(state.pipelineBusy || state.generating);
}

async function openPipelineReport(job, report, scroll = false) {
  switchTab("reports", false);
  await refresh({ scope: job.scope, day: report.business_date });
  if (scroll) $("main").scrollIntoView();
}

function renderPipeline(job) {
  state.pipelineBusy = job?.status === "running";
  updateDatasetButtons();
  $("run-pipeline").textContent = state.pipelineBusy ? "Reconciliation running…" :
    job?.status === "complete" ? "Run again" : job ? "Retry reconciliation" : "Run reconciliation";
  $("pipeline-steps").replaceChildren(...Object.entries(pipelineSteps).map(([key, label]) => {
    const detail = job?.steps[key];
    const active = job?.stage === key;
    const status = active && job.status === "failed" ? "Failed" :
      active && state.pipelineBusy ? "Running" : detail ? "Complete" : "Waiting";
    const step = el("li");
    step.dataset.state = status;
    if (active && state.pipelineBusy) step.setAttribute("aria-current", "step");
    step.append(el("strong", label), el("span", status + (detail ? " · " + detail : "")));
    return step;
  }));
  const status = !job ? "Waiting for a run." : job.error || (state.pipelineBusy ?
    pipelineSteps[job.stage] + " · " + job.steps[job.stage] :
    "Evaluation complete. " + job.reports.length + " daily reports ready.");
  if ($("pipeline-status").textContent !== status) $("pipeline-status").textContent = status;
  const reports = job?.reports || [];
  const reportIds = reports.map((report) => report.result_id).join(",");
  if ($("pipeline-results").dataset.reports !== reportIds) {
    $("pipeline-results").dataset.reports = reportIds;
    $("pipeline-results").replaceChildren(...reports.map((report) => {
      const button = el("button", "Report · " + dateLabel(report.business_date), "button quiet");
      button.type = "button";
      button.addEventListener("click", () => openPipelineReport(job, report, true));
      return button;
    }));
  }
  renderEvaluation(job?.evaluation);
}

function renderEvaluation(evaluation) {
  $("evaluation").hidden = !evaluation;
  if (!evaluation) {
    $("evaluation-cases").open = false;
    return;
  }
  const days = evaluation.business_dates;
  $("evaluation-context").textContent = dateLabel(days[0]) + (days.length > 1 ?
    " – " + dateLabel(days.at(-1)) : "") + " · Synthetic seed " + evaluation.seed;
  const falseMatches = Object.values(evaluation.false_matches).reduce((total, count) => total + count, 0);
  const breakdown = evaluation.false_matches;
  $("evaluation-summary").replaceChildren(...[
    ["False matches", falseMatches, [`${breakdown.exact} exact`, `${breakdown.diagnostic} amount check`,
      `${breakdown.fuzzy} fuzzy`].join(" · ")],
    ["Correct links", evaluation.true_links - evaluation.missed_true_links,
      "of " + integer.format(evaluation.true_links) + " true links"],
    ["Missed true links", evaluation.missed_true_links],
  ].map(([label, value, description]) => {
    const card = el("dl", null, "metric");
    card.append(el("dt", label), el("dd", integer.format(value)));
    if (description) card.append(el("dd", description, "metric-note"));
    return card;
  }));
  $("evaluation-metrics").replaceChildren(...Object.entries(evaluation.error_metrics).map(([category, score]) => {
    const row = el("tr");
    const label = el("th", categories[category]);
    label.scope = "row";
    row.append(label);
    for (const value of [score.precision, score.recall]) {
      row.append(el("td", value === null ? "—" : percent.format(value)));
    }
    row.append(el("td", integer.format(score.tp)), el("td", integer.format(score.support)));
    return row;
  }));
  $("evaluation-notes").textContent = integer.format(evaluation.excluded_invalid_rows) +
    " invalid input rows excluded from scoring. — indicates no cases to calculate the rate.";
  const misses = evaluation.misses;
  const reasons = Object.entries(misses.reason_counts);
  $("evaluation-reasons").replaceChildren(...(reasons.length ?
    reasons.map(([reason, count]) => el("li", integer.format(count) + " · " + reason)) :
    [el("li", "Every eligible true link was found.")]));
  $("evaluation-cases").hidden = !misses.cases.length;
  $("evaluation-case-list").replaceChildren(...misses.cases.map((item) => {
    const entry = el("li");
    entry.append(el("strong", item.label), el("p", item.detail),
      el("p", "Ledger " + item.ledger + " · Expected settlement " + item.true_settlement, "case-identity"));
    if (item.candidates.length) {
      const candidates = el("ul", null, "case-candidates");
      candidates.append(...item.candidates.map((candidate) => el("li",
        candidate.ledger_reference + " → " + candidate.settlement_reference + " · " + candidate.score + "/100")));
      entry.append(candidates);
    }
    return entry;
  }));
}

async function followPipeline(job) {
  if (!job || job.dataset_id !== state.dataset?.id || state.following) return;
  state.following = true;
  try {
    renderPipeline(job);
    while (job.status === "running") {
      await new Promise((resolve) => setTimeout(resolve, 350));
      job = await request("/api/pipeline");
      if (!job || job.dataset_id !== state.dataset?.id) {
        throw new Error("This run is no longer active. Use Run reconciliation to resume it.");
      }
      renderPipeline(job);
    }
  } catch (error) {
    state.pipelineBusy = false;
    updateDatasetButtons();
    $("run-pipeline").textContent = "Run reconciliation";
    $("pipeline-status").textContent = error.message;
  } finally {
    state.following = false;
  }
}

async function runPipeline() {
  state.pipelineBusy = true;
  updateDatasetButtons();
  notice("dataset-status", "");
  try {
    const job = await request("/api/datasets/" + state.dataset.id + "/reconcile", {});
    await followPipeline(job);
  } catch (error) {
    state.pipelineBusy = false;
    updateDatasetButtons();
    notice("dataset-status", error.message);
  }
}

async function generateDataset() {
  const button = $("generate-dataset");
  state.generating = true;
  updateDatasetButtons();
  button.textContent = "Generating…";
  notice("dataset-status", "Generating the ledger and settlements…");
  try {
    const dataset = await request("/api/datasets", {});
    showDataset(dataset);
    if (dataset.cleanup_pending) {
      notice("dataset-status", "New dataset ready. Some old files could not be removed from disk.");
    } else {
      notice("dataset-status", "New dataset ready. Only this dataset is available.", true);
    }
  } catch (error) {
    notice("dataset-status", error.message);
  } finally {
    button.textContent = "Generate dataset";
    state.generating = false;
    updateDatasetButtons();
  }
}

for (const [key, label] of Object.entries(categories)) $("category").add(new Option(label, key));
$("pipeline-tab").addEventListener("click", () => switchTab("pipeline"));
$("reports-tab").addEventListener("click", () => switchTab("reports"));
$("issues-tab").addEventListener("click", () => switchTab("issues"));
$("refresh").addEventListener("click", () => state.tab === "pipeline" ? start() : refresh());
$("generate-dataset").addEventListener("click", generateDataset);
$("run-pipeline").addEventListener("click", runPipeline);
$("scope").addEventListener("change", () => { fillDays(); act(() => loadTab(true)); });
$("day").addEventListener("change", () => act(() => loadTab(true)));
$("snapshot").addEventListener("change", () => act(loadReport));
$("filters").addEventListener("submit", (event) => { event.preventDefault(); act(() => loadQueue(false)); });
$("more").addEventListener("click", () => act(() => loadQueue(true)));
$("close").addEventListener("click", () => $("issue-detail").close());
$("reload-issue").addEventListener("click", () => openIssue(state.issue.id)
  .catch((error) => notice("issue-notice", error.message)));
$("review").addEventListener("submit", saveReview);

async function start() {
  const key = new URLSearchParams(location.hash.slice(1)).get("access");
  if (key) {
    window.history.replaceState(null, "", location.pathname);
    try {
      await request("/api/session", { key });
    } catch (error) {
      connection("Sign-in needed", false);
      notice("notice", error.message);
      return;
    }
  }
  if (state.generating || state.following) return;
  state.generating = true;
  updateDatasetButtons();
  try {
    const dataset = await request("/api/datasets/current");
    if (dataset) showDataset(dataset);
    const job = await request("/api/pipeline");
    await refresh();
    if (job && job.dataset_id === state.dataset?.id) await followPipeline(job);
  } catch (error) {
    connection(error.status === 401 ? "Sign-in needed" : "Disconnected", false);
    notice("dataset-status", error.message);
  } finally {
    state.generating = false;
    updateDatasetButtons();
  }
}
window.addEventListener("hashchange", () => {
  if (new URLSearchParams(location.hash.slice(1)).has("access")) start();
});
renderPipeline(null);
start();
