"use strict";

/* Platform super-admin console: approve organizer accounts + oversee every league
   (including handing a league's manager role to one of its participating pilots). */

const $ = (id) => document.getElementById(id);
const esc = SKORE.escapeHtml;

// --- organizer account approval ---------------------------------------------
async function loadOrganizers() {
  const res = await SKORE.api("/api/admin/organizers");
  if (!res.ok) { $("status").textContent = "운영자 목록을 불러오지 못했습니다."; return; }
  const { organizers } = await res.json();
  const pending = organizers.filter((o) => o.status === "pending");
  $("org-count").textContent = pending.length ? `승인 대기 ${pending.length}명` : "";
  const chip = (s) => ({
    active: `<span class="statuschip approved">승인됨</span>`,
    pending: `<span class="statuschip pending">대기</span>`,
    rejected: `<span class="statuschip rejected">거절됨</span>`,
  }[s] || esc(s));
  const head = `<thead><tr><th class="l">이름</th><th class="l">이메일</th><th class="l">상태</th><th></th></tr></thead>`;
  if (!organizers.length) {
    $("org-table").innerHTML = head + `<tbody><tr><td colspan="4" class="muted" style="padding:10px">운영자 계정이 없습니다.</td></tr></tbody>`;
    return;
  }
  const body = organizers.map((o) => {
    const actions = o.status === "active"
      ? `<button class="rowbtn del" data-reject="${o.uid}">승인취소</button>`
      : `<button class="rowbtn save" data-approve="${o.uid}">승인</button>` +
        (o.status === "pending" ? `<button class="rowbtn del" data-reject="${o.uid}">거절</button>` : "");
    return `<tr>
      <td class="l">${esc(o.display_name) || "—"}</td>
      <td class="l num">${esc(o.email) || "—"}</td>
      <td class="l">${chip(o.status)}</td>
      <td class="actions">${actions}</td></tr>`;
  }).join("");
  $("org-table").innerHTML = head + `<tbody>${body}</tbody>`;
  wireOrg();
}

function wireOrg() {
  const on = (attr, action) => $("org-table").querySelectorAll(`[data-${attr}]`).forEach((b) =>
    b.addEventListener("click", () => setOrg(b.dataset[attr], action)));
  on("approve", "approve");
  on("reject", "reject");
}

async function setOrg(uid, action) {
  const res = await SKORE.api(`/api/admin/organizers/${uid}/${action}`, { method: "POST" });
  if (res.ok) loadOrganizers();
  else alert("처리 실패");
}

// --- all leagues + owner transfer -------------------------------------------
let leagues = [];

async function loadLeagues() {
  const res = await SKORE.api("/api/admin/leagues");
  if (!res.ok) return;
  leagues = (await res.json()).leagues;
  $("league-count").textContent = leagues.length ? `${leagues.length}개` : "";
  render();
}

function render(openId) {
  const head = `<thead><tr><th class="l">리그</th><th class="l">운영자</th><th class="l">차전</th><th></th></tr></thead>`;
  if (!leagues.length) {
    $("league-table").innerHTML = head + `<tbody><tr><td colspan="4" class="muted" style="padding:10px">리그가 없습니다.</td></tr></tbody>`;
    return;
  }
  const body = leagues.map((l) => {
    const row = `<tr data-lid="${l.id}">
      <td class="l">${esc(l.name)}</td>
      <td class="l num">${esc(l.owner_email) || "<span class='muted'>(없음)</span>"}</td>
      <td class="l num">${l.meet_count != null ? l.meet_count + "차전" : "—"}</td>
      <td class="actions"><button class="rowbtn edit" data-transfer="${l.id}">운영자 변경</button></td></tr>`;
    const panel = l.id === openId
      ? `<tr class="transfer-row"><td colspan="4" style="padding:10px 8px">
           <span class="muted" style="margin-right:8px">이 리그 참가 선수 중 새 운영자 선택:</span>
           <select id="tr-sel-${l.id}"></select>
           <button class="rowbtn save" data-apply="${l.id}">적용</button>
           <button class="rowbtn" data-cancel="1">취소</button>
           <span id="tr-msg-${l.id}" class="muted" style="margin-left:8px"></span></td></tr>`
      : "";
    return row + panel;
  }).join("");
  $("league-table").innerHTML = head + `<tbody>${body}</tbody>`;
  wireLeagues();
  if (openId) fillTransfer(openId);
}

function wireLeagues() {
  const q = (attr, fn) => $("league-table").querySelectorAll(`[data-${attr}]`).forEach((b) =>
    b.addEventListener("click", () => fn(b.dataset[attr])));
  q("transfer", (lid) => render(lid));
  q("cancel", () => render());
  q("apply", (lid) => applyTransfer(lid));
}

// Load the league's participating pilots (accounts) into the transfer <select>.
async function fillTransfer(lid) {
  const sel = $(`tr-sel-${lid}`);
  const msg = $(`tr-msg-${lid}`);
  sel.innerHTML = `<option value="">불러오는 중…</option>`;
  const res = await SKORE.api(`/api/leagues/${lid}/registrations`);
  if (!res.ok) { sel.innerHTML = `<option value="">불러오기 실패</option>`; return; }
  const pilots = (await res.json()).registrations.filter((r) => r.uid);
  if (!pilots.length) { sel.innerHTML = `<option value="">계정 연결된 참가 선수 없음</option>`; msg.textContent = "가입해 참가 신청한 선수만 지정할 수 있습니다."; return; }
  sel.innerHTML = `<option value="">— 선수 선택 —</option>` +
    pilots.map((p) => `<option value="${p.uid}">${esc(p.name)}${p.account_email ? " (" + esc(p.account_email) + ")" : ""}</option>`).join("");
}

async function applyTransfer(lid) {
  const uid = $(`tr-sel-${lid}`).value;
  if (!uid) { $(`tr-msg-${lid}`).textContent = "선수를 선택하세요."; return; }
  if (!confirm("이 선수를 리그 운영자로 지정합니다. 계속할까요?")) return;
  const res = await SKORE.api(`/api/admin/leagues/${lid}/transfer-owner`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uid }),
  });
  if (res.ok) { await loadLeagues(); }
  else { const e = await res.json().catch(() => ({})); $(`tr-msg-${lid}`).textContent = "실패: " + (e.detail || res.status); }
}

// --- gate: admins only ------------------------------------------------------
(async () => {
  const user = await SKORE.renderAuthNav($("authbar"), { style: "panel" });
  if (!user) { location.href = "/login.html"; return; }
  if (user.role !== "admin") { location.href = SKORE.home(user); return; }
  loadOrganizers();
  loadLeagues();
})();
