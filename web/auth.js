"use strict";

/* Shared SKORE auth helpers. Session is an httpOnly cookie set by the API, so
   this script never touches the token directly — it asks /api/auth/me. */
const SKORE = (() => {
  const escapeHtml = (s) =>
    String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function me() {
    try {
      const r = await fetch("/api/auth/me");
      if (!r.ok) return null;
      return (await r.json()).user || null;
    } catch {
      return null;
    }
  }

  async function logout() {
    try { await fetch("/api/auth/logout", { method: "POST" }); } catch {}
    location.href = "/";
  }

  const roleLabel = (r) => (r === "organizer" ? "운영자" : "참가자");
  const home = (u) => (!u ? "/" : u.role === "organizer" ? "/comp.html" : "/dashboard.html");

  /* Render login/signup or user+logout into a container.
     style: "nav" (landing top bar) | "panel" (app sidebar). */
  async function renderAuthNav(el, { style = "nav" } = {}) {
    const u = await me();
    if (!el) return u;
    if (u) {
      el.innerHTML =
        `<a href="${home(u)}" class="authuser"><span class="rolechip">${roleLabel(u.role)}</span>${escapeHtml(u.display_name)}</a>` +
        `<button type="button" class="btn secondary btn-sm" data-logout>로그아웃</button>`;
    } else if (style === "panel") {
      el.innerHTML =
        `<a href="/login.html" class="link">로그인</a>` +
        `<a href="/signup.html" class="btn primary btn-sm">회원가입</a>`;
    } else {
      el.innerHTML =
        `<a href="/login.html" class="link">로그인</a>` +
        `<a href="/signup.html" class="btn primary btn-sm">회원가입</a>`;
    }
    el.querySelector("[data-logout]")?.addEventListener("click", logout);
    return u;
  }

  /* Guard a page: require a logged-in user (optionally a specific role).
     Redirects to /login.html if unauthorized. Returns the user when allowed. */
  async function requireRole(role = null, redirect = "/login.html") {
    const u = await me();
    if (!u || (role && u.role !== role)) {
      location.href = redirect;
      return null;
    }
    return u;
  }

  return { me, logout, renderAuthNav, requireRole, roleLabel, home, escapeHtml };
})();
