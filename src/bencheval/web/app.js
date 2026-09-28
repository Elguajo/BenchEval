"use strict";
const $ = id => document.getElementById(id);
let runs = [];
let selected = null;
let detailRequest = 0;
let panelId = 0;
const axisLabels = {outcome: "Outcome", instruction_fidelity: "Instruction fidelity", behavior: "Behavior"};
const knownStates = new Set(["PASS", "FAIL", "INCONCLUSIVE", "NOT_OBSERVABLE", "NOT_APPLICABLE", "ERROR", "PENDING", "INVALID"]);
function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = String(text);
  if (className) node.className = className;
  return node;
}
function badge(state) {
  const node = element("span", state, "badge");
  node.dataset.state = knownStates.has(state) ? state : "ERROR";
  return node;
}
async function get(url) {
  const response = await fetch(url, {cache: "no-store"});
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || "Unable to read local artifacts.");
  return data;
}
function renderList() {
  $("runs").replaceChildren();
  const query = $("search").value.toLowerCase();
  const kind = $("kind").value;
  const visible = runs.filter(run => (kind === "all" || run.kind === kind) &&
    `${run.name} ${run.id}`.toLowerCase().includes(query));
  for (const run of visible) {
    const button = element("button", undefined, "run");
    button.type = "button";
    button.setAttribute("aria-pressed", String(selected === `${run.kind}/${run.id}`));
    const line = element("span", undefined, "run-title");
    line.append(element("strong", run.kind === "actor" ? run.name : "Judge · " + run.name), badge(run.overall));
    button.append(line, element("span", run.id, "run-id"), element("span", `${run.kind} · ${run.status}`, "muted"));
    button.addEventListener("click", () => selectRun(run));
    $("runs").append(button);
  }
  if (!visible.length) $("runs").append(element("p", runs.length ? "No runs match these filters." :
    "No saved runs yet. Run a scenario with the CLI, then refresh.", "muted"));
}
function block(title, value) {
  const section = element("section", undefined, "evidence-block");
  section.append(element("h3", title), element("pre", typeof value === "string" ? value : JSON.stringify(value, null, 2)));
  return section;
}
function disclosure(title, className, children, open = false) {
  const section = element("section", undefined, className);
  const button = element("button", undefined, "disclosure");
  button.type = "button";
  const caret = element("span", open ? "▾" : "▸", "caret");
  caret.setAttribute("aria-hidden", "true");
  button.append(caret, typeof title === "string" ? element("span", title) : title);
  const body = element("div");
  body.id = `evidence-panel-${++panelId}`;
  body.hidden = !open;
  body.append(...children);
  button.setAttribute("aria-controls", body.id);
  button.setAttribute("aria-expanded", String(open));
  button.addEventListener("click", () => {
    body.hidden = !body.hidden;
    button.setAttribute("aria-expanded", String(!body.hidden));
    caret.textContent = body.hidden ? "▸" : "▾";
  });
  section.append(button, body);
  return section;
}
async function selectRun(run) {
  selected = `${run.kind}/${run.id}`;
  const request = ++detailRequest;
  renderList();
  $("detail").replaceChildren(element("p", "Verifying evidence…", "muted"));
  try {
    const data = await get(`/api/runs/${selected}`);
    if (request !== detailRequest) return;
    const fragment = document.createDocumentFragment();
    const header = element("div", undefined, "run-heading");
    const heading = element("div");
    const title = element("h2", data.kind === "actor" ? data.name : "Judge verdict");
    title.id = "detail-title";
    title.tabIndex = -1;
    heading.append(element("p", data.kind === "actor" ? "Actor execution" : "Independent judge", "eyebrow"),
      title, element("p", data.id, "run-id"));
    header.append(heading, badge(data.verdicts ? data.verdicts.overall : "PENDING"));
    fragment.append(header, element("p", `Evidence hashes verified · ${data.status}`, "muted"));
    if (data.actor_run_id) {
      const source = element("button", "View original actor run", "source-link");
      source.type = "button";
      source.addEventListener("click", () => selectRun({kind: "actor", id: data.actor_run_id}));
      fragment.append(source);
    }
    const axes = element("div", undefined, "axes");
    for (const [axis, label] of Object.entries(axisLabels)) {
      const card = element("section", undefined, "axis");
      card.append(element("h3", label), badge(data.verdicts ? data.verdicts.axes[axis] : "PENDING"));
      axes.append(card);
    }
    fragment.append(axes);
    for (const warning of data.warnings) fragment.append(element("p", warning, "notice"));
    fragment.append(element("h3", "Checks and findings", "section-title"));
    if (!data.checks.length) fragment.append(element("p", "No verdict yet. Exported jobs require a judge run or desktop reply import.", "muted"));
    for (const check of data.checks) {
      const line = element("span", undefined, "check-heading");
      line.append(element("span", check.id), badge(check.state), element("span", check.severity, "severity"));
      const item = disclosure(line, "check", [element("p", check.actual), block("Requirement", check.expected),
        element("p", `Axes: ${check.axes.map(axis => axisLabels[axis]).join(" · ")}`, "muted"),
        element("p", `Evidence: ${check.evidence.join(", ") || "not available"}`, "run-id")],
        check.state === "FAIL" || check.state === "ERROR");
      fragment.append(item);
    }
    fragment.append(element("h3", "Preserved evidence", "section-title"));
    for (const [name, content] of Object.entries(data.evidence)) {
      fragment.append(disclosure(name, "evidence", [block(name, content)], name === "response"));
    }
    const metadata = disclosure("Runtime and context metadata", "evidence", [block("Metadata", data.metadata)]);
    fragment.append(metadata);
    $("detail").replaceChildren(fragment);
  } catch (error) {
    if (request !== detailRequest) return;
    $("detail").replaceChildren(element("h2", "Run unavailable"), element("p", error.message, "notice"));
    const retry = element("button", "Retry");
    retry.type = "button";
    retry.addEventListener("click", () => selectRun(run));
    $("detail").append(retry);
  }
}
async function refresh() {
  $("refresh").disabled = true;
  $("count").textContent = "Loading saved runs…";
  try {
    const data = await get("/api/runs");
    runs = data.runs;
    $("count").textContent = data.total > data.limit ? `${data.runs.length} newest of ${data.total} saved runs` : `${data.total} saved runs`;
    renderList();
    if (selected) {
      const [kind, id] = selected.split("/");
      await selectRun({kind, id});
    }
  } catch (error) {
    $("count").textContent = error.message + " Use Refresh to retry.";
  } finally { $("refresh").disabled = false; }
}
$("search").addEventListener("input", renderList);
$("kind").addEventListener("change", renderList);
$("refresh").addEventListener("click", refresh);
refresh();
