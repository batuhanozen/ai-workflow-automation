"use strict";
const $ = (selector) => document.querySelector(selector);
const state = {
  key: "",
  tab: "all",
  offset: 0,
  limit: 8,
  config: null,
  detail: null,
  loading: false,
};
const categories = [
  "IT Support",
  "Software Issue",
  "Account Access",
  "Infrastructure",
  "Security",
  "General Request",
];
const priorities = ["Low", "Medium", "High", "Critical"];
const esc = (value) =>
  String(value ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const date = (value) =>
  new Date(value).toLocaleString([], {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
const badge = (value) =>
  `<span class="badge ${esc(String(value).toLowerCase())}">${esc(value)}</span>`;
let toastTimer;
function toast(message, error = false) {
  $("#toast").textContent = message;
  $("#toast").className = error ? "error" : "";
  $("#toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => {
    $("#toast").hidden = true;
  }, 6000);
}
async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(state.key ? { "X-API-Key": state.key } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    let data;
    try {
      data = await response.json();
    } catch {
      data = {};
    }
    if (response.status === 401 && !$("#access-dialog").open)
      $("#access-dialog").showModal();
    throw new Error(
      typeof data.detail === "string"
        ? data.detail
        : `Request failed (${response.status})`,
    );
  }
  return response.json();
}
async function refresh() {
  if (state.loading) return;
  state.loading = true;
  try {
    const params = new URLSearchParams({
      limit: state.limit,
      offset: state.offset,
      q: $("#search").value,
    });
    if ($("#status-filter").value)
      params.set("status", $("#status-filter").value);
    if ($("#priority-filter").value)
      params.set("priority", $("#priority-filter").value);
    if (state.tab === "review") params.set("needs_review", "true");
    if (state.tab === "reviewed") params.set("reviewed", "true");
    const [stats, requests, activity] = await Promise.all([
      api("/stats"),
      api(`/requests?${params}`),
      api("/activity"),
    ]);
    $("#activity").innerHTML = activity.length
      ? activity
          .map(
            (a) =>
              `<button class="activity-item" data-id="${a.request_id}"><span class="activity-dot">↳</span><span><strong>${esc(a.event)}</strong><small>${esc(a.title)}</small></span><time>${date(a.created_at)}</time></button>`,
          )
          .join("")
      : '<p class="muted">Your workflow activity will appear here.</p>';
    for (const key of [
      "total",
      "processed",
      "needs_review",
      "pending",
      "failed",
    ])
      $(`#stat-${key}`).textContent = stats[key];
    $("#nav-count").textContent = stats.needs_review;
    const highest = Math.max(1, ...Object.values(stats.by_category));
    $("#categories").innerHTML = categories
      .map(
        (c) =>
          `<div class="bar-row"><span>${c}</span><progress class="bar-track" max="${highest}" value="${stats.by_category[c] || 0}" aria-label="${c}"></progress><b>${stats.by_category[c] || 0}</b></div>`,
      )
      .join("");
    $("#priorities").innerHTML = priorities
      .map(
        (p) =>
          `<div class="priority-box"><strong>${stats.by_priority[p] || 0}</strong>${badge(p)}</div>`,
      )
      .join("");
    $("#request-count").textContent = requests.total;
    $("#empty").hidden = requests.items.length > 0;
    $("#request-rows").innerHTML = requests.items
      .map(
        (r) =>
          `<tr><td><button class="request-link" data-id="${r.id}">${esc(r.title)}</button><small>${r.id.slice(0, 8).toUpperCase()} · ${r.provider === "mock" ? "Mock provider" : r.provider === "openai" ? "LLM provider" : "Awaiting analysis"}</small></td><td>${esc(r.classification?.category || "—")}</td><td>${r.classification ? badge(r.classification.priority) : "—"}</td><td>${badge(r.status)}</td><td class="review-indicator">${r.reviewed ? "✓ Reviewed" : "○ Unreviewed"}</td><td>${date(r.created_at)}</td><td><button class="text-button" data-id="${r.id}" aria-label="Open ${esc(r.title)}">↗</button></td></tr>`,
      )
      .join("");
    $("#page-label").textContent = requests.total
      ? `Showing ${state.offset + 1}–${Math.min(state.offset + state.limit, requests.total)} of ${requests.total} requests`
      : "No matching requests";
    $("#previous").disabled = state.offset === 0;
    $("#next").disabled = state.offset + state.limit >= requests.total;
  } catch (error) {
    toast(error.message, true);
  } finally {
    state.loading = false;
  }
}
function options(items, current) {
  return items
    .map(
      (item) =>
        `<option${item === current ? " selected" : ""}>${esc(item)}</option>`,
    )
    .join("");
}
async function openDetail(id) {
  try {
    const r = await api(`/requests/${id}`);
    state.detail = r;
    $("#detail-id").textContent =
      `REQUEST ${r.id.slice(0, 8).toUpperCase()} · ${date(r.created_at)}`;
    $("#detail-title").textContent = r.title;
    const c = r.classification;
    $("#detail-body").innerHTML =
      `<div class="result-meta">${badge(r.status)}${r.provider ? badge(r.provider === "mock" ? "Mock provider" : "LLM provider") : ""}${r.reviewed ? badge("Human reviewed") : ""}</div><p class="description">${esc(r.description)}</p>
      ${r.is_fallback ? '<p class="warning">AI processing failed. The fallback below is a manual-triage placeholder, not a successful AI classification. Review the actual urgency.</p>' : ""}
      ${c ? `<section class="detail-section"><h3>Current classification ${r.reviewed ? "· human reviewed" : "· automated"}</h3><div class="result-meta">${badge(c.category)}${badge(c.priority)}<span class="badge">AI confidence ${Math.round(c.confidence * 100)}% · uncalibrated</span></div><p class="description">${esc(c.summary)}</p><p class="evidence">“${esc(c.evidence)}”</p><p class="description"><strong>Suggested action:</strong> ${esc(c.suggested_action)}</p><p class="muted">Action ${r.action_approved ? "approved by a reviewer" : "awaiting approval"}. Approval records a decision; no external action is executed.</p></section>` : '<p class="muted">Processing is in progress. Close and reopen this request to check its result.</p>'}
      ${c && ["completed", "failed"].includes(r.status) ? `<section class="detail-section"><h3>Human review</h3><form id="review-form"><div class="result-grid"><label>Category<select name="category">${options(categories, c.category)}</select></label><label>Priority<select name="priority">${options(priorities, c.priority)}</select></label></div><label>Suggested action<textarea name="suggested_action" required minlength="5" maxlength="600" rows="2">${esc(c.suggested_action)}</textarea></label><label>Your display name<input name="reviewer" required minlength="2" maxlength="80" placeholder="e.g. Demo reviewer"></label><label>Review note<textarea name="note" required minlength="5" maxlength="1000" rows="2" placeholder="Explain your decision or correction"></textarea></label><label class="checkbox"><input type="checkbox" name="action_approved" ${r.action_approved ? "checked" : ""}>Approve this suggested action</label><div class="form-footer">${r.status === "failed" && !r.reviewed ? '<button type="button" class="secondary" id="retry">Retry AI processing</button>' : ""}<button class="primary" type="submit">Save review</button></div></form></section>` : ""}
      <section class="detail-section"><h3>Processing & review history</h3>${r.results.map((result) => `<details><summary>${date(result.created_at)} · ${esc(result.provider)} · ${result.is_fallback ? "Fallback" : "Validated"} · ${result.attempts} attempt(s)</summary><p class="muted">Model: ${esc(result.model)} · ${esc(result.prompt_version)} · ${result.duration_ms} ms</p><pre>${esc(JSON.stringify(result.classification, null, 2))}</pre></details>`).join("")}${r.errors.map((e) => `<div class="history-entry"><strong>${esc(e.code)}</strong> · ${esc(e.message)}<br><small>${date(e.created_at)} · attempt ${e.attempt}${e.details.length ? ` · ${esc(JSON.stringify(e.details))}` : ""}</small></div>`).join("")}${r.reviews.map((v) => `<div class="history-entry"><strong>${esc(v.reviewer)}</strong> → ${esc(v.category)} / ${esc(v.priority)} · action ${v.action_approved ? "approved" : "not approved"}<p>${esc(v.note)}</p><small>${date(v.created_at)} · AI result #${v.result_id}</small></div>`).join("")}</section>`;
    if (!$("#detail-dialog").open) $("#detail-dialog").showModal();
    $("#review-form")?.addEventListener("submit", submitReview);
    $("#retry")?.addEventListener("click", async (event) => {
      event.target.disabled = true;
      try {
        await api(`/requests/${id}/retry`, { method: "POST" });
        $("#detail-dialog").close();
        toast("Queued for another processing attempt.");
        await refresh();
      } catch (error) {
        toast(error.message, true);
        event.target.disabled = false;
      }
    });
  } catch (error) {
    toast(error.message, true);
  }
}
async function submitReview(event) {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector("[type=submit]");
  button.disabled = true;
  const data = Object.fromEntries(new FormData(form));
  data.action_approved = form.elements.action_approved.checked;
  data.expected_version = state.detail.version;
  try {
    await api(`/requests/${state.detail.id}/reviews`, {
      method: "POST",
      body: JSON.stringify(data),
    });
    toast("Review saved. Original AI result preserved.");
    await openDetail(state.detail.id);
    await refresh();
  } catch (error) {
    toast(error.message, true);
    button.disabled = false;
  }
}
function setTab(tab) {
  state.tab = tab;
  state.offset = 0;
  document
    .querySelectorAll("[data-tab]")
    .forEach((b) => b.classList.toggle("selected", b.dataset.tab === tab));
  refresh();
}
document
  .querySelectorAll("[data-close]")
  .forEach((b) =>
    b.addEventListener("click", () => b.closest("dialog").close()),
  );
document
  .querySelectorAll("[data-tab]")
  .forEach((b) => b.addEventListener("click", () => setTab(b.dataset.tab)));
$("#new-request").addEventListener("click", () =>
  $("#create-dialog").showModal(),
);
$("#access-button").addEventListener("click", () =>
  $("#access-dialog").showModal(),
);
$("#access-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  state.key = event.target.elements.key.value;
  event.target.reset();
  $("#access-dialog").close();
  await init();
});
$("#activity").addEventListener("click", (event) => {
  const b = event.target.closest("[data-id]");
  if (b) openDetail(b.dataset.id);
});
$("#request-rows").addEventListener("click", (event) => {
  const b = event.target.closest("[data-id]");
  if (b) openDetail(b.dataset.id);
});
$("#create-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const button = form.querySelector("[type=submit]");
  button.disabled = true;
  try {
    await api("/requests", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    form.reset();
    $("#create-dialog").close();
    state.offset = 0;
    toast("Request received. Analysis is queued.");
    await refresh();
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
});
$("#refresh").addEventListener("click", refresh);
$("#previous").addEventListener("click", () => {
  state.offset = Math.max(0, state.offset - state.limit);
  refresh();
});
$("#next").addEventListener("click", () => {
  state.offset += state.limit;
  refresh();
});
for (const id of ["status-filter", "priority-filter"])
  $(`#${id}`).addEventListener("change", () => {
    state.offset = 0;
    refresh();
  });
let searchTimer;
$("#search").addEventListener("input", () => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    state.offset = 0;
    refresh();
  }, 250);
});
$("#nav-review").addEventListener("click", () => {
  setTab("review");
  $("#requests-section").scrollIntoView({ behavior: "smooth" });
});
$("#nav-requests").addEventListener("click", () => {
  setTab("all");
  $("#requests-section").scrollIntoView({ behavior: "smooth" });
});
async function init() {
  try {
    state.config = await api("/config");
    $("#provider").textContent =
      state.config.provider === "mock" ? "◉ Mock provider" : "◉ Live LLM";
    $("#mode-title").textContent =
      state.config.provider === "mock"
        ? "Demo mode is active"
        : "Live AI analysis";
    $("#mode-description").textContent =
      state.config.provider === "mock"
        ? "Deterministic classifications. No API key or paid calls needed."
        : "Structured outputs, evidence checks, and a complete audit trail.";
    await refresh();
  } catch (error) {
    toast(error.message, true);
  }
}
init();
setInterval(() => {
  if (!document.hidden && !document.querySelector("dialog[open]")) refresh();
}, 5000);
