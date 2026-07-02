"use strict";

let leagueId = null;
let rows = [];          // full registration rows for the current league
let editingPid = null;

const $ = (id) => document.getElementById(id);
const esc = SKORE.escapeHtml;

// EN class dropdown for inline editing (CCC/D/C/B/A + 미지정).
function classSelect(current) {
  const cur = (current || "").toUpperCase();
  return `<select class="e-class">` +
    ["", "CCC", "D", "C", "B", "A"].map((v) =>
      `<option value="${v}"${v === cur ? " selected" : ""}>${v || "등급 —"}</option>`).join("") +
    `</select>`;
}

// --- load owned leagues into the picker --------------------------------------
async function loadLeagues() {
  const { leagues } = await (await fetch("/api/leagues?mine=1")).json();
  const sel = $("league-select");
  sel.innerHTML = `<option value="">— 리그를 선택 —</option>` +
    leagues.map((l) => `<option value="${l.id}">${esc(l.name)} (${l.meet_count}차전)</option>`).join("");
  if (!leagues.length) { $("status").textContent = "소유한 리그가 없습니다. ‘리그 채점’에서 리그를 만들거나 미소유 리그를 가져오세요."; return; }
  const want = location.hash.slice(1);   // deep link from the console (#leagueId)
  if (want && leagues.some((l) => l.id === want)) { sel.value = want; selectLeague(want); }
}

$("league-select").addEventListener("change", (e) => {
  if (e.target.value) selectLeague(e.target.value);
  else { leagueId = null; $("roster-view").hidden = true; $("empty").hidden = false; }
});

async function selectLeague(id) {
  leagueId = id;
  const res = await fetch(`/api/leagues/${id}/registrations`);
  if (!res.ok) { $("status").textContent = "명단을 불러오지 못했습니다."; return; }
  rows = (await res.json()).registrations;
  editingPid = null;
  $("league-title").textContent = $("league-select").selectedOptions[0].textContent.replace(/\s*\(\d+차전\)$/, "");
  $("empty").hidden = true;
  $("roster-view").hidden = false;
  render();
}

// --- render ------------------------------------------------------------------
function statusOf(r) { return r.status || "approved"; }

function render() {
  const pending = rows.filter((r) => statusOf(r) === "pending" || statusOf(r) === "rejected");
  const approved = rows.filter((r) => statusOf(r) === "approved");
  renderPending(pending);
  renderApproved(approved);
}

function renderPending(list) {
  $("pending-count").textContent = list.length ? `${list.length}명` : "";
  if (!list.length) { $("pending-table").innerHTML = `<tbody><tr><td class="muted" style="padding:10px">대기 중인 참가 신청이 없습니다.</td></tr></tbody>`; return; }
  const head = `<thead><tr><th class="bib">배번</th><th class="l">이름</th><th class="l">기체</th><th class="l">등급</th>` +
    `<th class="l">연락처</th><th class="l">계정</th><th class="l">상태</th><th></th></tr></thead>`;
  const body = list.map((r) => {
    const rejected = statusOf(r) === "rejected";
    const chip = rejected ? `<span class="statuschip rejected">거절됨</span>` : `<span class="statuschip pending">대기</span>`;
    const actions = rejected
      ? `<button class="rowbtn edit" data-approve="${r.pid}">승인</button>
         <button class="rowbtn del" data-del="${r.pid}" title="삭제">✕</button>`
      : `<button class="rowbtn save" data-approve="${r.pid}">승인</button>
         <button class="rowbtn del" data-reject="${r.pid}" title="거절">거절</button>`;
    return `<tr data-pid="${r.pid}">
      <td class="bib">${esc(r.bib) || "—"}</td>
      <td class="l">${esc(r.name)}</td>
      <td class="l num">${esc(r.glider) || "—"}</td>
      <td class="l num">${esc(r.glider_class) || "—"}</td>
      <td class="l num">${esc(r.contact) || "—"}</td>
      <td class="l num">${esc(r.account_email) || "—"}</td>
      <td class="l">${chip}</td>
      <td class="actions">${actions}</td></tr>`;
  }).join("");
  $("pending-table").innerHTML = head + `<tbody>${body}</tbody>`;
  wire($("pending-table"));
}

function renderApproved(list) {
  $("approved-count").textContent = list.length ? `${list.length}명` : "";
  const head = `<thead><tr><th class="bib">배번</th><th class="l">이름</th><th class="l">기체</th><th class="l">등급</th>` +
    `<th class="l">연락처</th><th class="l">계정</th><th class="l">별칭</th><th></th></tr></thead>`;
  if (!list.length) { $("approved-table").innerHTML = head + `<tbody><tr><td colspan="8" class="muted" style="padding:10px">아직 승인된 선수가 없습니다.</td></tr></tbody>`; return; }
  const body = list.map((r) => r.pid === editingPid ? editRow(r) : viewRow(r)).join("");
  $("approved-table").innerHTML = head + `<tbody>${body}</tbody>`;
  wire($("approved-table"));
}

function sourceTag(r) {
  return r.source === "self" ? ` <span class="badge">신청</span>` : "";
}

function viewRow(r) {
  const aliases = (r.aliases || []).map(esc).join(", ");
  return `<tr data-pid="${r.pid}">
    <td class="bib">${esc(r.bib) || "—"}</td>
    <td class="l">${esc(r.name)}${sourceTag(r)}</td>
    <td class="l num">${esc(r.glider) || "—"}</td>
    <td class="l num">${esc(r.glider_class) || "—"}</td>
    <td class="l num">${esc(r.contact) || "—"}</td>
    <td class="l num">${esc(r.account_email) || "—"}</td>
    <td class="l num">${aliases || "—"}</td>
    <td class="actions">
      <button class="rowbtn edit" data-edit="${r.pid}">수정</button>
      <button class="rowbtn del" data-del="${r.pid}" title="삭제">✕</button>
    </td></tr>`;
}

function editRow(r) {
  const aliases = (r.aliases || []).join(", ");
  return `<tr data-pid="${r.pid}" class="editing">
    <td class="bib"><input class="e-bib" type="text" value="${esc(r.bib)}" placeholder="배번" /></td>
    <td class="l"><input class="e-name" type="text" value="${esc(r.name)}" placeholder="이름" /></td>
    <td class="l"><input class="e-glider" type="text" value="${esc(r.glider)}" placeholder="기체" /></td>
    <td class="l">${classSelect(r.glider_class)}</td>
    <td class="l"><input class="e-contact" type="text" value="${esc(r.contact)}" placeholder="연락처" /></td>
    <td class="l num">${esc(r.account_email) || "—"}</td>
    <td class="l"><input class="e-aliases" type="text" value="${esc(aliases)}" placeholder="별칭 (쉼표)" /></td>
    <td class="actions">
      <button class="rowbtn save" data-save="${r.pid}">저장</button>
      <button class="rowbtn cancel" data-cancel="${r.pid}">취소</button>
    </td></tr>`;
}

// --- wiring ------------------------------------------------------------------
function wire(table) {
  const on = (attr, fn) => table.querySelectorAll(`[data-${attr}]`).forEach((b) =>
    b.addEventListener("click", () => fn(b.dataset[attr], b.closest("tr"))));
  on("approve", (pid) => setStatus(pid, "approve"));
  on("reject", (pid) => setStatus(pid, "reject"));
  on("edit", (pid) => { editingPid = pid; render(); });
  on("cancel", () => { editingPid = null; render(); });
  on("del", (pid) => deletePilot(pid));
  on("save", (pid, tr) => savePilot(pid, tr));
  table.querySelectorAll("tr.editing input").forEach((inp) =>
    inp.addEventListener("keydown", (ev) => { if (ev.key === "Enter") savePilot(ev.target.closest("tr").dataset.pid, ev.target.closest("tr")); }));
}

async function setStatus(pid, action) {
  const res = await fetch(`/api/leagues/${leagueId}/registrations/${pid}/${action}`, { method: "POST" });
  if (res.ok) await selectLeague(leagueId);
  else alert("처리 실패");
}

async function savePilot(pid, tr) {
  const fd = new FormData();
  fd.append("bib", tr.querySelector(".e-bib").value);
  fd.append("name", tr.querySelector(".e-name").value);
  fd.append("glider", tr.querySelector(".e-glider").value);
  fd.append("glider_class", tr.querySelector(".e-class").value);
  fd.append("contact", tr.querySelector(".e-contact").value);
  fd.append("aliases", tr.querySelector(".e-aliases").value);
  const res = await fetch(`/api/leagues/${leagueId}/roster/${pid}`, { method: "PATCH", body: fd });
  if (res.ok) { editingPid = null; await selectLeague(leagueId); }
  else alert("저장 실패");
}

async function deletePilot(pid) {
  const r = rows.find((x) => x.pid === pid);
  if (!confirm(`"${r ? r.name : pid}" 선수를 명단에서 삭제할까요?`)) return;
  const res = await fetch(`/api/leagues/${leagueId}/roster/${pid}`, { method: "DELETE" });
  if (res.ok) { if (editingPid === pid) editingPid = null; await selectLeague(leagueId); }
  else alert("삭제 실패");
}

// --- gate: organizers only ---------------------------------------------------
(async () => {
  const user = await SKORE.renderAuthNav($("authbar"), { style: "panel" });
  if (!user) { location.href = "/login.html"; return; }
  if (user.role !== "organizer") { location.href = SKORE.home(user); return; }
  loadLeagues();
})();
