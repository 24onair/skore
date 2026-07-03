"use strict";

/* Shared SKORE auth helpers, backed by Supabase Auth (GoTrue).

   Load order (every page): <script src="supabase-js CDN"> → config.js → auth.js.
   The Supabase client keeps the session in localStorage and refreshes the access
   token automatically. `api()` attaches that token as `Authorization: Bearer` so our
   own /api endpoints can verify it. `me()` returns the app profile (role + pilot
   fields) from /api/auth/me. */
const SKORE = (() => {
  const cfg = window.SKORE_CONFIG || {};
  const sb = window.supabase.createClient(cfg.url, cfg.anonKey, {
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
  });

  const escapeHtml = (s) =>
    String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  async function token() {
    const { data } = await sb.auth.getSession();
    return data.session?.access_token || null;
  }

  /* fetch() wrapper that attaches the Supabase access token. Same call sites as the
     old bare fetch(), just via SKORE.api(). Returns the raw Response. */
  async function api(path, opts = {}) {
    const t = await token();
    const headers = new Headers(opts.headers || {});
    if (t) headers.set("Authorization", "Bearer " + t);
    return fetch(path, { ...opts, headers });
  }

  async function me() {
    const t = await token();
    if (!t) return null;
    try {
      const r = await api("/api/auth/me");
      if (!r.ok) return null;
      return (await r.json()).user || null;
    } catch {
      return null;
    }
  }

  async function login(email, password) {
    const { data, error } = await sb.auth.signInWithPassword({ email, password });
    if (error) throw new Error(error.message || "로그인 실패");
    return data;
  }

  /* Sign up; role + pilot fields go into user metadata, which the
     on_auth_user_created DB trigger copies into public.profiles. */
  async function signup(email, password, meta) {
    const { data, error } = await sb.auth.signUp({ email, password, options: { data: meta } });
    if (error) throw new Error(error.message || "가입 실패");
    return data;
  }

  async function logout() {
    try { await sb.auth.signOut(); } catch {}
    location.href = "/";
  }

  /* Upload IGC File objects to the private `igc` bucket and return short-lived
     signed URLs for the scoring endpoint. Keeps large uploads off our function. */
  async function uploadIGCs(files, signedSeconds = 900) {
    const { data: { user } } = await sb.auth.getUser();
    const uid = user?.id || "anon";
    const urls = [];
    let i = 0;
    for (const f of files) {
      const safe = (f.name || "track.igc").replace(/[^A-Za-z0-9._-]/g, "_");
      const path = `${uid}/${Date.now()}-${i++}-${safe}`;
      const up = await sb.storage.from("igc").upload(path, f, { upsert: true, contentType: "text/plain" });
      if (up.error) throw new Error(`업로드 실패(${f.name}): ${up.error.message}`);
      const sig = await sb.storage.from("igc").createSignedUrl(path, signedSeconds);
      if (sig.error) throw new Error(`서명 URL 실패(${f.name}): ${sig.error.message}`);
      urls.push(sig.data.signedUrl);
    }
    return urls;
  }

  async function readText(file) {
    return await file.text();
  }

  const roleLabel = (r) =>
    r === "admin" ? "관리자" : r === "organizer" ? "운영자" : "참가자";
  const home = (u) => {
    if (!u) return "/";
    if (u.role === "admin") return "/admin.html";
    if (u.role === "organizer") return "/comp.html";
    return "/dashboard.html";
  };

  /* Render login/signup or user+logout into a container.
     style: "nav" (landing top bar) | "panel" (app sidebar). */
  async function renderAuthNav(el, { style = "nav" } = {}) {
    const u = await me();
    if (!el) return u;
    if (u) {
      el.innerHTML =
        `<a href="${home(u)}" class="authuser"><span class="rolechip">${roleLabel(u.role)}</span>${escapeHtml(u.display_name)}</a>` +
        `<button type="button" class="btn secondary btn-sm" data-logout>로그아웃</button>`;
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

  return {
    sb, api, me, token, login, signup, logout, uploadIGCs, readText,
    renderAuthNav, requireRole, roleLabel, home, escapeHtml,
  };
})();
