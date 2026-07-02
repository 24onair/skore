"use strict";

const $ = (id) => document.getElementById(id);

(async () => {
  // gate: participants only (organizers go to their league console)
  const user = await SKORE.me();
  if (!user) { location.href = "/login.html"; return; }
  if (user.role !== "participant") { location.href = SKORE.home(user); return; }

  SKORE.renderAuthNav($("authbar"));

  $("hello").textContent = `${user.display_name} 님의 성적`;
  const esc = SKORE.escapeHtml;
  const parts = [`매칭 기준: <b>${esc(user.pilot_name || user.display_name)}</b>`];
  if (user.bib) parts.push(`배번 ${esc(user.bib)}`);
  if (user.glider) parts.push(`기체 ${esc(user.glider)}`);
  if (user.glider_class) parts.push(`등급 ${esc(user.glider_class)}`);
  if (user.contact) parts.push(`연락처 ${esc(user.contact)}`);
  $("profile-line").innerHTML =
    parts.join(" · ") +
    ` <a href="#" id="edit-profile" style="color:var(--accent);text-decoration:none;font-size:12px">(수정)</a>`;
  $("edit-profile").addEventListener("click", (e) => { e.preventDefault(); editProfile(user); });

  await Promise.all([loadResults(), loadJoin()]);
})();

// --- league join / membership status ----------------------------------------
async function loadJoin() {
  const [leaguesRes, memRes] = await Promise.all([
    SKORE.api("/api/leagues"),
    SKORE.api("/api/me/memberships"),
  ]);
  const { leagues } = await leaguesRes.json();
  const { memberships } = await memRes.json();
  const status = {};
  for (const m of memberships) status[m.league_id] = m.status;
  const box = $("join-list");
  if (!leagues.length) { box.innerHTML = `<div class="muted">아직 개설된 리그가 없습니다.</div>`; return; }

  const chip = (s) => ({
    approved: `<span class="statuschip approved">승인됨</span>`,
    pending: `<span class="statuschip pending">승인 대기</span>`,
    rejected: `<span class="statuschip rejected">거절됨</span>`,
  }[s] || "");

  box.innerHTML = leagues.map((l) => {
    const s = status[l.id];
    const right = s
      ? chip(s)
      : `<button class="btn primary btn-sm" data-join="${l.id}">참가 신청</button>`;
    return `<div class="join-row">
       <div><div class="jl-name">${SKORE.escapeHtml(l.name)}</div>
         <div class="muted" style="font-size:12px">${l.meet_count}차전</div></div>
       <div>${right}</div>
     </div>`;
  }).join("");

  box.querySelectorAll("[data-join]").forEach((b) =>
    b.addEventListener("click", () => joinLeague(b.dataset.join)));
}

async function joinLeague(id) {
  const res = await SKORE.api(`/api/leagues/${id}/register`, { method: "POST" });
  if (res.ok) { await loadJoin(); }
  else { const e = await res.json().catch(() => ({})); alert("신청 실패: " + (e.detail || res.status)); }
}

async function loadResults() {
  const res = await SKORE.api("/api/me/results");
  if (!res.ok) { location.href = "/login.html"; return; }
  const { results } = await res.json();
  const cards = $("cards");
  if (!results.length) { $("empty").hidden = false; cards.innerHTML = ""; return; }
  $("empty").hidden = true;

  cards.innerHTML = results.map((r) => {
    const meets = r.meets.map((m) =>
      `<tr>
         <td class="l">${SKORE.escapeHtml(m.name)}</td>
         <td class="tot">${m.points != null ? m.points : "—"}</td>
       </tr>`).join("");
    const medal = r.rank === 1 ? "rank1" : "";
    return `<div class="my-card">
      <div class="my-head">
        <div>
          <div class="my-league">${SKORE.escapeHtml(r.league_name)}</div>
          <div class="muted" style="font-size:12px;margin-top:3px">${r.field_size}명 중</div>
        </div>
        <div class="my-rank ${medal}">
          <div class="rk">${r.rank === 1 ? "★ " : ""}${r.rank}<small>위</small></div>
          <div class="pts">${r.total} <small>점</small></div>
        </div>
      </div>
      <div class="tablewrap">
        <table class="rank">
          <thead><tr><th class="l">차전</th><th>내 점수</th></tr></thead>
          <tbody>${meets}</tbody>
        </table>
      </div>
    </div>`;
  }).join("");
}

function editProfile(user) {
  const name = prompt("트랙 표기 이름 (IGC에 찍히는 이름)", user.pilot_name || user.display_name);
  if (name === null) return;
  const bib = prompt("배번 (없으면 비움)", user.bib || "");
  if (bib === null) return;
  const glider = prompt("기체 (없으면 비움)", user.glider || "");
  if (glider === null) return;
  let gclass = prompt("기체 등급 — CCC / D / C / B / A (없으면 비움)", user.glider_class || "");
  if (gclass === null) return;
  gclass = gclass.trim().toUpperCase();
  if (gclass && !["CCC", "D", "C", "B", "A"].includes(gclass)) {
    alert("등급은 CCC, D, C, B, A 중 하나여야 합니다."); return;
  }
  const contact = prompt("연락처 (운영자에게만 표시, 없으면 비움)", user.contact || "");
  if (contact === null) return;
  const fd = new FormData();
  fd.append("pilot_name", name);
  fd.append("bib", bib);
  fd.append("glider", glider);
  fd.append("glider_class", gclass);
  fd.append("contact", contact);
  SKORE.api("/api/me/profile", { method: "PATCH", body: fd }).then((r) => {
    if (r.ok) location.reload();
    else alert("프로필 수정 실패");
  });
}
