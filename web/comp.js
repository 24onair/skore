"use strict";

let TZ_OFFSET = 0;
let league = null;   // current league detail
let meet = null;     // current meet detail (null → league view)
let editingPid = null;
let currentTaskId = null;   // task shown in the detail panel (for filter re-render)

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const normName = (s) => String(s || "").replace(/\s+/g, "").toLowerCase();

// --- glider class (EN) grouping for split standings --------------------------
// D and CCC always share one group; C, B, A are their own groups.
const CLASS_GROUP = { CCC: "CCC+D", D: "CCC+D", C: "C", B: "B", A: "A" };
const CLASS_FILTERS = ["전체", "CCC+D", "C", "B", "A"];
const classGroupOf = (cls) => (cls ? (CLASS_GROUP[String(cls).toUpperCase()] || null) : null);

// A <select> of EN classes with `current` preselected (for inline roster editing).
function classSelectHTML(cls, current) {
  const cur = (current || "").toUpperCase();
  const opts = ["", "CCC", "D", "C", "B", "A"].map((v) =>
    `<option value="${v}"${v === cur ? " selected" : ""}>${v || "등급 —"}</option>`).join("");
  return `<select class="${cls}">${opts}</select>`;
}

// Fill a class-filter <select> once, preserving the chosen value across renders.
function ensureClassFilter(sel) {
  if (!sel.options.length) {
    sel.innerHTML = CLASS_FILTERS.map((f) =>
      `<option value="${f}">${f === "전체" ? "전체 등급" : f + " 등급"}</option>`).join("");
  }
  return sel.value || "전체";
}

// Filter rows to a class group ("전체" = all) then re-rank 1..n by total desc
// (ties share a rank) — mirrors store._rank so each group ranks from 1위.
function applyClassFilter(rows, group) {
  const out = (!group || group === "전체")
    ? rows.slice()
    : rows.filter((r) => classGroupOf(r.glider_class) === group);
  let prevTotal = null, prevRank = 0;
  out.forEach((r, i) => {
    if (prevTotal === null || Math.abs(r.total - prevTotal) > 1e-9) {
      r.rank = i + 1; prevRank = i + 1; prevTotal = r.total;
    } else { r.rank = prevRank; }
  });
  return out;
}

function durToHMS(s) {
  if (s == null) return "—";
  const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
  return h > 0 ? `${h}:${String(m).padStart(2, "0")}:${String(sec).padStart(2, "0")}`
              : `${m}:${String(sec).padStart(2, "0")}`;
}

// Resolve a result row to a roster pilot (mirrors server: bib first, then name).
function matchRoster(row) {
  const roster = (league && league.roster) || [];
  const bib = String(row.bib || "").trim();
  if (bib) { const p = roster.find((r) => String(r.bib || "").trim() === bib); if (p) return p; }
  const n = normName(row.name);
  return roster.find((r) =>
    normName(r.name) === n || (r.aliases || []).some((a) => normName(a) === n)) || null;
}

// --- leagues list (organizer's own leagues only) ----------------------------
async function loadLeagues(selectId) {
  const { leagues } = await (await fetch("/api/leagues?mine=1")).json();
  const sel = $("league-select");
  sel.innerHTML = `<option value="">— 리그를 선택 —</option>` +
    leagues.map((l) => `<option value="${l.id}">${esc(l.name)} (${l.meet_count}차전)</option>`).join("");
  if (selectId) sel.value = selectId;
}

$("league-select").addEventListener("change", (e) => {
  if (e.target.value) selectLeague(e.target.value);
  else showEmpty();
});

// class-filter selects re-render the matching standings view (no data refetch)
$("league-class-filter").addEventListener("change", () => { if (league) renderLeagueStandings(); });
$("meet-class-filter").addEventListener("change", () => {
  if (meet) { renderMeetStandings(); if (!$("task-detail").hidden && currentTaskId) showTask(currentTaskId); }
});

function showEmpty() {
  league = null; meet = null;
  $("league-view").hidden = true; $("meet-view").hidden = true;
  $("empty").hidden = false; $("crumb").hidden = true;
}

// --- create league ----------------------------------------------------------
$("new-league-btn").addEventListener("click", () => {
  $("create-form").hidden = !$("create-form").hidden;
});

$("create-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData();
  fd.append("name", $("c-name").value);
  fd.append("nominal_distance", String(Number($("c-nomdist").value) * 1000));
  fd.append("nominal_time", String(Number($("c-nomtime").value) * 60));
  fd.append("nominal_launch", String(Number($("c-nomlaunch").value) || 0));
  fd.append("nominal_goal", String(Number($("c-nomgoal").value) || 0.25));
  fd.append("min_distance", String(Number($("c-mindist").value) * 1000));
  fd.append("leading_time_ratio", String(Number($("c-ltr").value) || 0.26));
  const lg = await (await fetch("/api/leagues", { method: "POST", body: fd })).json();
  $("create-form").hidden = true;
  $("create-form").reset();
  await loadLeagues(lg.id);
  selectLeague(lg.id);
});

// --- select / render league -------------------------------------------------
async function selectLeague(id) {
  const res = await fetch(`/api/leagues/${id}`);
  if (!res.ok) return;
  league = await res.json();
  meet = null;
  renderLeague();
  $("empty").hidden = true;
  $("meet-view").hidden = true;
  $("league-view").hidden = false;
  $("crumb").hidden = false;
  $("crumb").innerHTML = `📍 <b>${esc(league.name)}</b>`;
  // clear any stale status/error left from a previous action
  const st = $("status"); st.className = "muted";
  st.textContent = "차전을 추가하거나 선수를 등록하세요.";
}

function renderLeague() {
  $("league-title").textContent = league.name;
  const p = league.params;
  $("league-params").innerHTML = [
    ["Nom.dist", `${p.nominal_distance / 1000} km`],
    ["Nom.time", `${Math.round(p.nominal_time / 60)} 분`],
    ["Nom.launch", p.nominal_launch],
    ["Min.dist", `${p.min_distance / 1000} km`],
    ["LTR", p.leading_time_ratio],
    ["차전", `${league.meets.length}개`],
  ].map(([k, v]) => `<div class="chip">${k} <b>${v}</b></div>`).join("");
  renderRoster();
  renderLeagueStandings();
  renderMeetList();
}

// --- roster (league-level) --------------------------------------------------
// Names that appeared on tracks but match no roster pilot — the candidate aliases.
function unmatchedNames() {
  const seen = new Set(), out = [];
  for (const s of (league.standings || [])) {
    if (!s.registered && s.name && !seen.has(s.name)) { seen.add(s.name); out.push(s.name); }
  }
  return out;
}

// Fill a <select> with unmatched track names (combo picker for aliases).
function fillAliasPicker(sel, exclude) {
  const names = unmatchedNames().filter((n) => !exclude.includes(n));
  if (!names.length) { sel.hidden = true; sel.innerHTML = ""; return; }
  sel.hidden = false;
  sel.innerHTML = `<option value="">+ 트랙 이름에서 별칭 추가…</option>` +
    names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("");
}

// Append a picked name into a comma-separated alias text input.
function appendAlias(input, value) {
  if (!value) return;
  const cur = input.value.split(",").map((s) => s.trim()).filter(Boolean);
  if (!cur.includes(value)) cur.push(value);
  input.value = cur.join(", ");
}

function renderRoster() {
  const roster = league.roster || [];
  const approvals = $("roster-approvals");
  if (approvals) approvals.href = `/roster.html#${league.id}`;
  $("roster-count").textContent = roster.length ? `${roster.length}명 등록` : "미등록 — IGC에서 가져오거나 직접 추가하세요";
  fillAliasPicker($("p-alias-pick"), []);  // keep the add-form combo in sync
  if (!roster.length) { $("roster-table").innerHTML = ""; return; }
  const head = `<thead><tr><th class="bib">배번</th><th class="l">이름</th><th class="l">기체</th><th class="l">등급</th>` +
    `<th class="l">별칭 <small class="muted">(트랙의 다른 표기)</small></th><th></th></tr></thead>`;
  const body = roster.map((p) => p.pid === editingPid ? editRowHTML(p) : viewRowHTML(p)).join("");
  $("roster-table").innerHTML = head + `<tbody>${body}</tbody>`;
  wireRosterRows();
}

function viewRowHTML(p) {
  const aliases = (p.aliases || []).map(esc).join(", ");
  return `<tr data-pid="${p.pid}">
     <td class="bib">${esc(p.bib) || "—"}</td>
     <td class="l">${esc(p.name)}</td>
     <td class="l num">${esc(p.glider) || "—"}</td>
     <td class="l num">${esc(p.glider_class) || "—"}</td>
     <td class="l num">${aliases || "—"}</td>
     <td class="actions">
       <button class="rowbtn edit" title="수정">수정</button>
       <button class="rowbtn del" title="삭제">✕</button>
     </td></tr>`;
}

function editRowHTML(p) {
  const aliases = (p.aliases || []).join(", ");
  const names = unmatchedNames().filter((n) => n !== p.name && !(p.aliases || []).includes(n));
  const picker = names.length
    ? `<select class="e-alias-pick"><option value="">+ 트랙 이름에서 추가…</option>` +
        names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("") + `</select>`
    : "";
  return `<tr data-pid="${p.pid}" class="editing">
     <td class="bib"><input class="e-bib" type="text" value="${esc(p.bib)}" placeholder="배번" /></td>
     <td class="l"><input class="e-name" type="text" value="${esc(p.name)}" placeholder="이름" /></td>
     <td class="l"><input class="e-glider" type="text" value="${esc(p.glider)}" placeholder="기체" /></td>
     <td class="l">${classSelectHTML("e-class", p.glider_class)}</td>
     <td class="l">
       <input class="e-aliases" type="text" value="${esc(aliases)}" placeholder="예: SungHoon Son, 손성훈2" />
       ${picker}
     </td>
     <td class="actions">
       <button class="rowbtn save" title="저장">저장</button>
       <button class="rowbtn cancel" title="취소">취소</button>
     </td></tr>`;
}

function wireRosterRows() {
  const t = $("roster-table");
  t.querySelectorAll(".del").forEach((b) =>
    b.addEventListener("click", (e) => deletePilot(e.target.closest("tr").dataset.pid)));
  t.querySelectorAll(".edit").forEach((b) =>
    b.addEventListener("click", (e) => { editingPid = e.target.closest("tr").dataset.pid; renderRoster(); }));
  t.querySelectorAll(".cancel").forEach((b) =>
    b.addEventListener("click", () => { editingPid = null; renderRoster(); }));
  t.querySelectorAll(".save").forEach((b) =>
    b.addEventListener("click", (e) => savePilot(e.target.closest("tr"))));
  t.querySelectorAll(".e-alias-pick").forEach((sel) =>
    sel.addEventListener("change", (e) => {
      appendAlias(e.target.closest("tr").querySelector(".e-aliases"), e.target.value);
      e.target.value = "";
    }));
  t.querySelectorAll("tr.editing input").forEach((inp) =>
    inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") savePilot(ev.target.closest("tr")); }));
}

async function savePilot(tr) {
  const pid = tr.dataset.pid;
  const fd = new FormData();
  fd.append("bib", tr.querySelector(".e-bib").value);
  fd.append("name", tr.querySelector(".e-name").value);
  fd.append("glider", tr.querySelector(".e-glider").value);
  fd.append("glider_class", tr.querySelector(".e-class").value);
  fd.append("aliases", tr.querySelector(".e-aliases").value);
  const res = await fetch(`/api/leagues/${league.id}/roster/${pid}`, { method: "PATCH", body: fd });
  if (res.ok) { editingPid = null; await selectLeague(league.id); }
}

async function deletePilot(pid) {
  const res = await fetch(`/api/leagues/${league.id}/roster/${pid}`, { method: "DELETE" });
  if (res.ok) { if (editingPid === pid) editingPid = null; await selectLeague(league.id); }
}

$("roster-add-btn").addEventListener("click", () => {
  const f = $("pilot-form"); f.hidden = !f.hidden; if (!f.hidden) $("p-name").focus();
});
$("pilot-cancel").addEventListener("click", () => { $("pilot-form").hidden = true; $("pilot-form").reset(); });
$("p-alias-pick").addEventListener("change", (e) => {
  appendAlias($("p-aliases"), e.target.value);
  e.target.value = "";
});

$("pilot-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!league) return;
  const fd = new FormData();
  fd.append("bib", $("p-bib").value);
  fd.append("name", $("p-name").value);
  fd.append("glider", $("p-glider").value);
  fd.append("glider_class", $("p-class").value);
  fd.append("aliases", $("p-aliases").value);
  const res = await fetch(`/api/leagues/${league.id}/roster`, { method: "POST", body: fd });
  if (res.ok) { $("pilot-form").reset(); $("pilot-form").hidden = true; await selectLeague(league.id); }
});

$("roster-import").addEventListener("change", async (e) => {
  const files = e.target.files;
  if (!files.length) return;
  if (!league) { $("status").className = "muted"; $("status").textContent = "먼저 리그를 선택하세요."; e.target.value = ""; return; }
  const fd = new FormData();
  for (const f of files) fd.append("igcs", f);
  const status = $("status");
  status.className = "muted"; status.textContent = `${files.length}개 IGC에서 선수 추출 중…`;
  try {
    const res = await fetch(`/api/leagues/${league.id}/roster/import`, { method: "POST", body: fd });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "가져오기 실패");
    status.textContent = `${data.added}명 추가 (총 ${data.roster_size}명)`;
    await selectLeague(league.id);
  } catch (err) {
    status.className = "err"; status.textContent = "오류: " + err.message;
  } finally {
    e.target.value = "";
  }
});

// --- league standings (columns = meets) -------------------------------------
function renderLeagueStandings() {
  const meets = league.meets;
  const group = ensureClassFilter($("league-class-filter"));
  const rows = applyClassFilter(league.standings, group);
  const head = `<thead><tr><th>순위</th><th class="bib">배번</th><th class="l">선수</th><th class="l">기체</th><th class="l">등급</th>` +
    meets.map((m, i) => `<th title="${esc(m.name)}">${esc(m.name) || `M${i + 1}`}</th>`).join("") +
    `<th>종합</th></tr></thead>`;
  const body = rows.map((s) => {
    const cells = meets.map((m) => `<td class="num">${s.per_meet[m.id] != null ? s.per_meet[m.id] : "—"}</td>`).join("");
    const flag = s.registered ? "" : ` <span class="badge warn" title="로스터에 없는 선수">미등록</span>`;
    return `<tr${s.rank === 1 ? ' class="rank1"' : ''}><td class="rk">${s.rank}</td><td class="bib">${esc(s.bib) || "—"}</td>` +
      `<td class="l">${esc(s.name)}${flag}</td><td class="l num">${esc(s.glider) || "—"}</td><td class="l num">${esc(s.glider_class) || "—"}</td>` +
      `${cells}<td class="tot">${s.total}</td></tr>`;
  }).join("");
  const cols = meets.length + 6;
  const emptyMsg = meets.length ? "해당 등급의 선수가 없습니다." : "아직 차전이 없습니다.";
  $("league-standings-table").innerHTML = head +
    `<tbody>${body || `<tr><td colspan="${cols}" class="muted">${emptyMsg}</td></tr>`}</tbody>`;
  const gnote = group !== "전체" ? ` · ${group} 등급` : "";
  $("league-standings-note").textContent = (meets.length ? `· ${meets.length}개 차전 합산` : "") + gnote;
}

// --- meet list --------------------------------------------------------------
function renderMeetList() {
  if (!league.meets.length) { $("meet-list").innerHTML = `<div class="muted">차전을 추가하세요.</div>`; return; }
  $("meet-list").innerHTML = league.meets.map((m, i) =>
    `<div class="meet-row" data-id="${m.id}">
       <button class="taskcard" data-open="${m.id}">
         <div class="tc-top">${esc(m.name)}</div>
         <div class="tc-sub muted">타스크 ${m.task_count}개 · Nom.dist ${m.params.nominal_distance / 1000}km</div>
       </button>
       <button class="rowbtn del" data-del="${m.id}" title="차전 삭제">✕</button>
     </div>`).join("");
  $("meet-list").querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => openMeet(b.dataset.open)));
  $("meet-list").querySelectorAll("[data-del]").forEach((b) => {
    const m = league.meets.find((x) => x.id === b.dataset.del);
    b.addEventListener("click", () => deleteMeet(b.dataset.del, m.name, m.task_count));
  });
}

async function deleteMeet(id, name, taskCount) {
  const warn = taskCount
    ? `차전 "${name}"과(와) 그 안의 타스크 ${taskCount}개가 모두 삭제됩니다. 리그 종합에서도 빠집니다.`
    : `차전 "${name}"을(를) 삭제할까요?`;
  if (!confirm(warn)) return;
  const res = await fetch(`/api/leagues/${league.id}/meets/${id}`, { method: "DELETE" });
  if (res.ok) await selectLeague(league.id);   // 리그 종합 + 차전 목록 새로고침
  else { const e = await res.json().catch(() => ({})); alert("삭제 실패: " + (e.detail || res.status)); }
}

// --- create meet ------------------------------------------------------------
$("new-meet-btn").addEventListener("click", () => {
  const f = $("meet-form"); f.hidden = !f.hidden; if (!f.hidden) $("m-name").focus();
});
$("meet-cancel").addEventListener("click", () => { $("meet-form").hidden = true; $("meet-form").reset(); });

$("meet-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (!league) return;
  const fd = new FormData();
  fd.append("name", $("m-name").value);
  const res = await fetch(`/api/leagues/${league.id}/meets`, { method: "POST", body: fd });
  if (res.ok) {
    const { meet: saved } = await res.json();
    $("meet-form").reset(); $("meet-form").hidden = true;
    await selectLeague(league.id);
    openMeet(saved.id);
  }
});

// --- select / render meet ---------------------------------------------------
async function openMeet(meetId) {
  const res = await fetch(`/api/leagues/${league.id}/meets/${meetId}`);
  if (!res.ok) return;
  meet = await res.json();
  renderMeet();
  $("league-view").hidden = true;
  $("meet-view").hidden = false;
  $("task-detail").hidden = true;
  currentTaskId = null;
  $("crumb").innerHTML = `📍 <b>${esc(league.name)}</b> › ${esc(meet.name)}`;
  window.scrollTo({ top: 0 });
}

$("back-to-league").addEventListener("click", () => {
  meet = null;
  $("meet-view").hidden = true;
  $("league-view").hidden = false;
  $("crumb").innerHTML = `📍 <b>${esc(league.name)}</b>`;
});

function renderMeet() {
  $("meet-title").textContent = meet.name;
  const p = meet.params;
  $("meet-params").innerHTML = [
    ["Nom.dist", `${p.nominal_distance / 1000} km`],
    ["Nom.time", `${Math.round(p.nominal_time / 60)} 분`],
    ["Nom.launch", p.nominal_launch],
    ["Min.dist", `${p.min_distance / 1000} km`],
    ["타스크", `${meet.tasks.length}개`],
  ].map(([k, v]) => `<div class="chip">${k} <b>${v}</b></div>`).join("");
  renderMeetStandings();
  renderTaskList();
}

// --- meet standings (columns = tasks) ---------------------------------------
function renderMeetStandings() {
  const tasks = meet.tasks;
  const group = ensureClassFilter($("meet-class-filter"));
  const rows = applyClassFilter(meet.standings, group);
  const head = `<thead><tr><th>순위</th><th class="bib">배번</th><th class="l">선수</th><th class="l">기체</th><th class="l">등급</th>` +
    tasks.map((t, i) => `<th title="${esc(t.name)}">${esc(t.name) || `R${i + 1}`}</th>`).join("") +
    `<th>종합</th></tr></thead>`;
  const body = rows.map((s) => {
    const cells = tasks.map((t) => `<td class="num">${s.per_task[t.id] != null ? s.per_task[t.id] : "—"}</td>`).join("");
    const flag = s.registered ? "" : ` <span class="badge warn" title="로스터에 없는 선수">미등록</span>`;
    return `<tr${s.rank === 1 ? ' class="rank1"' : ''}><td class="rk">${s.rank}</td><td class="bib">${esc(s.bib) || "—"}</td>` +
      `<td class="l">${esc(s.name)}${flag}</td><td class="l num">${esc(s.glider) || "—"}</td><td class="l num">${esc(s.glider_class) || "—"}</td>` +
      `${cells}<td class="tot">${s.total}</td></tr>`;
  }).join("");
  const cols = tasks.length + 6;
  const emptyMsg = tasks.length ? "해당 등급의 선수가 없습니다." : "아직 타스크가 없습니다.";
  $("meet-standings-table").innerHTML = head +
    `<tbody>${body || `<tr><td colspan="${cols}" class="muted">${emptyMsg}</td></tr>`}</tbody>`;
  const gnote = group !== "전체" ? ` · ${group} 등급` : "";
  $("meet-standings-note").textContent = (tasks.length ? `· ${tasks.length}개 타스크 합산` : "") + gnote;
}

// --- task list --------------------------------------------------------------
function renderTaskList() {
  if (!meet.tasks.length) { $("task-list").innerHTML = `<div class="muted">타스크를 추가하세요.</div>`; return; }
  $("task-list").innerHTML = meet.tasks.map((t, i) =>
    `<div class="meet-row" data-id="${t.id}">
       <button class="taskcard" data-open="${t.id}">
         <div class="tc-top">${esc(t.name)}</div>
         <div class="tc-sub muted">${t.task_distance_km} km · 비행 ${t.num_flying} · 골 ${t.num_in_goal} · DQ ${t.day_quality}</div>
       </button>
       <button class="rowbtn del" data-del="${t.id}" title="타스크 삭제">✕</button>
     </div>`).join("");
  $("task-list").querySelectorAll("[data-open]").forEach((b) =>
    b.addEventListener("click", () => showTask(b.dataset.open)));
  $("task-list").querySelectorAll("[data-del]").forEach((b) => {
    const t = meet.tasks.find((x) => x.id === b.dataset.del);
    b.addEventListener("click", () => deleteTask(b.dataset.del, t.name));
  });
}

async function deleteTask(id, name) {
  if (!meet) return;
  if (!confirm(`타스크 "${name}"의 채점 결과를 삭제할까요? (차전·리그 종합에서도 빠집니다)`)) return;
  const meetId = meet.id;   // capture before selectLeague() resets `meet` to null
  const res = await fetch(`/api/leagues/${league.id}/meets/${meetId}/tasks/${id}`, { method: "DELETE" });
  if (res.ok) {
    if (currentTaskId === id) { currentTaskId = null; $("task-detail").hidden = true; }
    await selectLeague(league.id);   // refresh league standings (resets `meet`)
    await openMeet(meetId);          // reopen the meet view
  } else {
    const e = await res.json().catch(() => ({}));
    alert("삭제 실패: " + (e.detail || res.status));
  }
}

// --- add task ---------------------------------------------------------------
$("new-task-btn").addEventListener("click", () => {
  const f = $("task-form"); f.hidden = !f.hidden;
});

$("task-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const igcs = $("t-igcs").files, task = $("t-task").files[0];
  if (!igcs.length || !task || !meet) return;
  const btn = $("t-go"), status = $("status");
  btn.disabled = true; status.className = "muted"; status.textContent = `${igcs.length}명 채점 중…`;

  const fd = new FormData();
  for (const f of igcs) fd.append("igcs", f);
  fd.append("task", task);
  fd.append("task_name", $("t-name").value);
  fd.append("num_present", String(Number($("t-present").value) || 0));

  try {
    const res = await fetch(`/api/leagues/${league.id}/meets/${meet.id}/tasks`, { method: "POST", body: fd });
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      throw new Error(err.detail || "채점 실패");
    }
    const { task: saved } = await res.json();
    status.textContent = "타스크 추가됨";
    $("task-form").reset(); $("task-form").hidden = true;
    const meetId = meet.id;          // capture before selectLeague() resets `meet`
    await selectLeague(league.id);   // refresh league standings + roster
    await openMeet(meetId);          // refresh meet view
    showTask(saved.id);
  } catch (err) {
    status.className = "err"; status.textContent = "오류: " + err.message;
  } finally {
    btn.disabled = false;
  }
});

// --- task detail ------------------------------------------------------------
async function showTask(taskId) {
  const res = await fetch(`/api/leagues/${league.id}/meets/${meet.id}/tasks/${taskId}`);
  if (!res.ok) return;
  currentTaskId = taskId;
  const task = await res.json();
  const r = task.result;
  TZ_OFFSET = (r.meta && r.meta.utc_offset) || 0;
  const group = ensureClassFilter($("meet-class-filter"));
  const inGroup = (cls) => group === "전체" || classGroupOf(cls) === group;

  $("task-detail-title").textContent = `타스크 결과 — ${task.name}`;
  const q = r.day_quality, pool = r.pool;
  $("task-dq").innerHTML = [
    ["과제거리", `${r.task_distance_km} km`],
    ["비행/참가", `${r.num_flying}/${r.num_present}명`],
    ["골", `${r.num_in_goal}명`],
    ["Day quality", `<b>${q.quality}</b>`],
    ["Launch", q.launch], ["Distance", q.distance], ["Time", q.time],
    ["배분 거/시/리", `${pool.distance}/${pool.time}/${pool.leading}`],
  ].map(([k, v]) => `<div class="chip">${k} ${v}</div>`).join("");

  const flown = new Set();
  // map every scored result to its roster identity first (populates `flown`),
  // then filter to the class group and re-rank within it.
  let scored = r.results.map((p) => {
    const reg = matchRoster(p);
    if (reg) flown.add(reg.pid);
    return {
      p, reg,
      name: reg ? reg.name : p.name,
      bib: (reg && reg.bib) || p.bib,
      glider: (reg && reg.glider) || p.glider,
      gclass: reg ? (reg.glider_class || "") : "",
    };
  });
  if (group !== "전체") scored = scored.filter((row) => row.reg && inGroup(row.gclass));
  let pt = null, pr = 0;
  scored.forEach((row, i) => {
    const t = row.p.total;
    if (pt === null || Math.abs(t - pt) > 1e-9) { row.rank = i + 1; pr = i + 1; pt = t; }
    else { row.rank = pr; }
  });

  const scoredRows = scored.map((row) => {
    const p = row.p;
    const status = p.in_goal ? `<span class="badge g">GOAL</span>`
      : p.reached_ess ? `<span class="badge">ESS</span>` : `<span class="badge">착륙</span>`;
    const flag = row.reg ? "" : ` <span class="badge warn" title="로스터에 없는 선수">미등록</span>`;
    return `<tr${row.rank === 1 ? ' class="rank1"' : ''}>
      <td class="rk">${row.rank}</td><td class="bib">${esc(row.bib) || "—"}</td>
      <td class="l">${esc(row.name)}${flag}</td><td class="l num">${esc(row.glider) || "—"}</td>
      <td class="l num">${esc(row.gclass) || "—"}</td>
      <td class="num">${p.distance_km} km</td><td>${status}</td>
      <td class="num">${durToHMS(p.ss_time)}</td>
      <td class="num">${p.distance_points}</td><td class="num">${p.time_points}</td>
      <td class="num">${p.leading_points}</td><td class="tot">${p.total}</td>
    </tr>`;
  }).join("");

  // Registered pilots with no track for this task → listed below as 미참가 (DNS).
  const absent = (league.roster || []).filter((pl) =>
    !flown.has(pl.pid) && (group === "전체" || inGroup(pl.glider_class)));
  const absentRows = absent.map((pl) =>
    `<tr class="absent">
      <td class="rk">—</td><td class="bib">${esc(pl.bib) || "—"}</td>
      <td class="l">${esc(pl.name)} <span class="badge warn">미참가</span></td>
      <td class="l num">${esc(pl.glider) || "—"}</td>
      <td class="l num">${esc(pl.glider_class) || "—"}</td>
      <td class="num">—</td><td>—</td><td class="num">—</td>
      <td class="num">—</td><td class="num">—</td><td class="num">—</td><td class="tot">—</td>
    </tr>`).join("");

  $("task-rows").innerHTML = scoredRows + absentRows;
  if (absent.length) $("task-dq").innerHTML += `<div class="chip">미참가 <b>${absent.length}명</b></div>`;
  $("task-detail").hidden = false;
  $("task-detail").scrollIntoView({ behavior: "smooth", block: "start" });
}

// --- ownerless (pre-auth) leagues an organizer can claim --------------------
async function loadClaimable() {
  const { leagues } = await (await fetch("/api/leagues")).json();
  const orphans = leagues.filter((l) => !l.owner_id);
  const box = $("claim-box");
  if (!orphans.length) { box.hidden = true; return; }
  box.hidden = false;
  $("claim-list").innerHTML = orphans.map((l) =>
    `<button class="taskcard" data-id="${l.id}">
       <div class="tc-top">${esc(l.name)}</div>
       <div class="tc-sub muted">${l.meet_count}차전 · 클릭해 내 소유로 가져오기</div>
     </button>`).join("");
  $("claim-list").querySelectorAll(".taskcard").forEach((b) =>
    b.addEventListener("click", async () => {
      const res = await fetch(`/api/leagues/${b.dataset.id}/claim`, { method: "POST" });
      if (res.ok) { await loadLeagues(b.dataset.id); await loadClaimable(); selectLeague(b.dataset.id); }
    }));
}

// --- gate: organizers only --------------------------------------------------
(async () => {
  const user = await SKORE.renderAuthNav($("authbar"), { style: "panel" });
  if (!user) { location.href = "/login.html"; return; }
  if (user.role !== "organizer") { location.href = SKORE.home(user); return; }
  loadLeagues();
  loadClaimable();
})();
