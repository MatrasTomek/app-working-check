"use strict";
// Dashboard — wszystkie dane wstawiane wyłącznie przez textContent / createElement.

(() => {
  const $ = (id) => document.getElementById(id);
  const HEARTBEAT_MS = 20000;
  const POLL_RUNNING_MS = 2000;
  const POLL_LIVE_MS = 5000;
  const AGENTS_LIVE_MS = 10000;
  const COLOR_RE = /^#[0-9a-f]{6}$/i;

  const state = { live: false, timers: [], tab: "servers", projects: null };

  // --- DOM -------------------------------------------------------------------------------
  function h(tag, props, ...children) {
    const el = document.createElement(tag);
    for (const [key, value] of Object.entries(props || {})) {
      if (value === null || value === undefined || value === false) continue;
      if (key === "class") el.className = value;
      else if (key === "href") {
        const safe = safeUrl(value);
        if (!safe) continue;
        el.href = safe;
        el.target = "_blank";
        el.rel = "noopener noreferrer";
      } else if (key === "src") {
        if (typeof value === "string" && value.startsWith("/api/")) el.src = value;
      } else if (key === "text") el.textContent = value;
      else el.setAttribute(key, String(value));
    }
    for (const child of children.flat()) {
      if (child === null || child === undefined || child === false) continue;
      el.append(child instanceof Node ? child : document.createTextNode(String(child)));
    }
    return el;
  }

  function safeUrl(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value, location.origin);
      return url.protocol === "http:" || url.protocol === "https:" ? url.href : null;
    } catch {
      return null;
    }
  }

  function fmtTime(iso) {
    if (!iso) return "";
    const d = new Date(iso);
    return isNaN(d) ? "" : d.toLocaleString("pl-PL", { dateStyle: "short", timeStyle: "medium" });
  }

  function ago(iso) {
    const d = new Date(iso);
    if (isNaN(d)) return "";
    const s = Math.max(0, Math.round((Date.now() - d.getTime()) / 1000));
    if (s < 60) return `${s} s temu`;
    if (s < 3600) return `${Math.round(s / 60)} min temu`;
    if (s < 86400) return `${Math.round(s / 3600)} h temu`;
    return `${Math.round(s / 86400)} dni temu`;
  }

  // --- API -------------------------------------------------------------------------------
  class AuthError extends Error {}

  async function api(path, method = "GET", body) {
    const opts = { method, credentials: "same-origin", headers: {}, cache: "no-store" };
    if (method !== "GET") opts.headers["X-Dashboard"] = "1";
    if (body !== undefined) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(body);
    }
    const res = await fetch(path, opts);
    if (res.status === 401) throw new AuthError("Wymagane logowanie");
    let data = null;
    try { data = await res.json(); } catch { data = null; }
    if (!res.ok) throw new Error((data && data.error) || `Błąd ${res.status}`);
    return data;
  }

  // --- logowanie -------------------------------------------------------------------------
  function showLogin(message) {
    stopTimers();
    $("app").hidden = true;
    $("login").hidden = false;
    $("login-error").hidden = !message;
    $("login-error").textContent = message || "";
    $("token").focus();
  }

  async function showApp() {
    $("login").hidden = true;
    $("app").hidden = false;
    await refreshAll();
    const live = await api("/api/live");
    setLive(live.enabled);
  }

  $("login-form").addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const input = $("token");
    try {
      await api("/api/login", "POST", { token: input.value });
      input.value = "";
      await showApp();
    } catch (e) {
      input.value = "";
      showLogin(e instanceof AuthError ? "Nieprawidłowy token" : e.message);
    }
  });

  $("logout").addEventListener("click", async () => {
    try { await api("/api/live/stop", "POST"); } catch { /* bez znaczenia */ }
    try { await api("/api/logout", "POST"); } catch { /* bez znaczenia */ }
    showLogin();
  });

  // --- zakładki --------------------------------------------------------------------------
  document.querySelectorAll(".tabs [role=tab]").forEach((tab) => {
    tab.addEventListener("click", () => {
      state.tab = tab.dataset.tab;
      document.querySelectorAll(".tabs [role=tab]").forEach((t) =>
        t.setAttribute("aria-selected", String(t === tab)));
      for (const name of ["servers", "projects", "agents"]) $(`tab-${name}`).hidden = name !== state.tab;
    });
  });

  // --- render: Serwery -------------------------------------------------------------------
  function jobLine(el, data, what) {
    el.classList.toggle("error", Boolean(data.error));
    if (data.state === "running") el.textContent = `${what}: trwa sprawdzanie…`;
    else if (data.error) el.textContent = `${what}: ${data.error}`;
    else if (data.finished_at) el.textContent = `${what}: ${fmtTime(data.finished_at)}`;
    else el.textContent = `${what}: jeszcze nie sprawdzano — kliknij Odpytaj`;
  }

  function renderServers(data) {
    jobLine($("servers-state"), data, "Ostatnie sprawdzenie");
    const list = $("servers-list");
    const run = data.run;
    if (!run) { list.replaceChildren(); $("count-servers").textContent = ""; return; }
    const c = run.counts;
    $("count-servers").textContent = String(run.apps.length);
    $("count-servers").classList.toggle("bad", c.error > 0);
    if (!run.apps.length) {
      list.replaceChildren(h("p", { class: "empty", text: "Brak aplikacji w apps.yaml / DASHBOARD_GITHUB" }));
      return;
    }
    const order = { error: 0, warning: 1, ok: 2 };
    const apps = [...run.apps].sort((a, b) => order[a.status] - order[b.status] || a.name.localeCompare(b.name));
    list.replaceChildren(...apps.map((app) => {
      const issues = app.issues.map((i) => h("li", { class: i.severity, text: `${i.category}: ${i.message}` }));
      const shot = app.screenshot ? h("details", {}, h("summary", { text: "Zrzut ekranu" }),
        h("img", { class: "shot", src: app.screenshot, alt: `Zrzut ekranu: ${app.name}`, loading: "lazy" })) : null;
      return h("article", { class: "card" },
        h("div", { class: "card-head" },
          h("span", { class: `dot ${app.status}`, "aria-hidden": "true" }),
          h("div", { class: "name", text: app.name }),
          h("span", { class: `chip ${app.status}`, text: app.status_label })),
        h("div", { class: "meta" }, h("a", { href: app.url, text: app.url }),
          app.load_time_ms != null ? ` · ${(app.load_time_ms / 1000).toFixed(1)} s` : ""),
        issues.length ? h("details", { open: app.status === "error" ? "" : null },
          h("summary", { text: `Problemy (${issues.length})` }), h("ul", {}, issues)) : null,
        shot);
    }));
  }

  // --- render: Projekty ------------------------------------------------------------------
  function renderProjects(data) {
    jobLine($("projects-state"), data, "Ostatnie odświeżenie");
    state.projects = data.repos;
    const select = $("projects-status");
    const current = select.value;
    const labels = [...new Set((data.repos || []).map((r) => r.status ? r.status.label : "—"))].sort();
    select.replaceChildren(h("option", { value: "", text: "Wszystkie statusy" }),
      ...labels.map((l) => h("option", { value: l, text: l })));
    select.value = labels.includes(current) ? current : "";
    $("count-projects").textContent = data.repos ? String(data.repos.length) : "";
    drawProjects();
  }

  function drawProjects() {
    const list = $("projects-list");
    const repos = state.projects;
    if (!repos) { list.replaceChildren(); return; }
    const q = $("projects-search").value.trim().toLowerCase();
    const status = $("projects-status").value;
    const shown = repos.filter((r) =>
      (!status || (r.status ? r.status.label : "—") === status) &&
      (!q || `${r.full_name} ${r.description || ""} ${r.topics.join(" ")}`.toLowerCase().includes(q)));
    if (!shown.length) { list.replaceChildren(h("p", { class: "empty", text: "Brak projektów" })); return; }
    list.replaceChildren(...shown.map((r) => {
      const badge = h("span", { class: "chip", text: r.status ? r.status.label : "bez statusu" });
      if (r.status && COLOR_RE.test(r.status.color)) {
        badge.style.color = r.status.color;  // CSSOM — dozwolone przez CSP (bez atrybutu style)
        badge.style.borderColor = r.status.color;
      }
      const langs = r.languages.length
        ? r.languages.slice(0, 4).map((l) => `${l.name} ${Math.round(l.percent)}%`).join(", ")
        : (r.main_language || "");
      const issues = r.issues.length ? h("details", {},
        h("summary", { text: `Issues (${r.issues_count})` }),
        h("ul", {}, r.issues.map((i) => h("li", {}, h("a", { href: i.html_url, text: `#${i.number} ${i.title}` }))))) : null;
      return h("article", { class: "card" },
        h("div", { class: "card-head" },
          h("div", { class: "name" }, h("a", { href: r.html_url, text: r.full_name })),
          badge),
        r.description ? h("div", { class: "meta", text: r.description }) : null,
        h("div", { class: "meta" },
          [r.pushed_at ? `zmiana ${r.pushed_at}` : null, langs || null, r.private ? "prywatne" : null,
           !r.issues_enabled ? "issues wyłączone" : (r.issues_count === 0 ? "brak issues" : null)]
            .filter(Boolean).join(" · ")),
        r.app_url ? h("div", { class: "meta" }, "aplikacja: ", h("a", { href: r.app_url, text: r.app_url })) : null,
        r.topics.length ? h("div", { class: "tags" }, r.topics.map((t) => h("span", { class: "chip", text: t }))) : null,
        issues);
    }));
  }

  $("projects-search").addEventListener("input", drawProjects);
  $("projects-status").addEventListener("change", drawProjects);

  // --- render: Agenci --------------------------------------------------------------------
  const AGENT_CLASS = { "pracuje": "working", "czeka na Ciebie": "waiting", "bezczynny": "idle" };

  function renderAgents(data) {
    const c = data.counts;
    $("agents-state").textContent =
      `Pracuje: ${c["pracuje"]} · czeka na Ciebie: ${c["czeka na Ciebie"]} · bezczynne: ${c["bezczynny"]}`;
    $("count-agents").textContent = String(data.agents.length);
    $("count-agents").classList.toggle("good", c["pracuje"] > 0);
    const list = $("agents-list");
    if (!data.agents.length) {
      list.replaceChildren(h("p", { class: "empty", text: "Brak działających sesji Claude Code" }));
      return;
    }
    list.replaceChildren(...data.agents.map((a) => h("article", { class: "card" },
      h("div", { class: "card-head" },
        h("span", { class: `dot ${AGENT_CLASS[a.state] || "idle"}`, "aria-hidden": "true" }),
        h("div", { class: "name", text: a.title || a.project }),
        h("span", { class: "chip", text: a.state }),
        killButton(a)),
      h("div", { class: "meta", text: [a.project, a.branch].filter(Boolean).join(" · ") }),
      h("div", { class: "meta", text: [ago(a.last_activity), a.last_tool ? `ostatnio: ${a.last_tool}` : null]
        .filter(Boolean).join(" · ") }),
      a.pr_url ? h("div", { class: "meta" }, h("a", { href: a.pr_url, text: a.pr_url })) : null)));
  }

  function killButton(a) {
    const name = a.title || a.project;
    const btn = h("button", { class: "danger small", type: "button", text: "Kill",
      "aria-label": `Zakończ sesję: ${name}` });
    btn.addEventListener("click", () => guarded(async () => {
      if (!confirm(`Zakończyć proces sesji Claude Code?\n\n${name}\n${a.project}`)) return;
      btn.disabled = true;
      try {
        await api(`/api/agents/${encodeURIComponent(a.session_id)}/kill`, "POST");
        await new Promise((r) => setTimeout(r, 1000));  // proces potrzebuje chwili na zamknięcie
      } finally {
        renderAgents(await api("/api/agents"));
      }
    }));
    return btn;
  }

  // --- odświeżanie -----------------------------------------------------------------------
  async function guarded(fn) {
    try {
      return await fn();
    } catch (e) {
      if (e instanceof AuthError) showLogin("Sesja wygasła — zaloguj się ponownie");
      else $("updated").textContent = `Błąd: ${e.message}`;
      return null;
    }
  }

  async function refreshAll() {
    const [servers, projects, agents] = await Promise.all([
      api("/api/servers"), api("/api/projects"), api("/api/agents")]);
    renderServers(servers);
    renderProjects(projects);
    renderAgents(agents);
    $("updated").textContent = `Odświeżono ${fmtTime(new Date().toISOString())}`;
    return servers.state === "running" || projects.state === "running";
  }

  let runningPoll = null;
  function pollWhileRunning() {
    if (runningPoll) return;
    runningPoll = setInterval(() => guarded(async () => {
      const busy = await refreshAll();
      if (!busy) { clearInterval(runningPoll); runningPoll = null; }
    }), POLL_RUNNING_MS);
  }

  $("btn-query").addEventListener("click", () => guarded(async () => {
    $("btn-query").disabled = true;
    try {
      const [s, p] = await Promise.all([api("/api/servers/check", "POST"), api("/api/projects/refresh", "POST")]);
      renderServers(s);
      renderProjects(p);
      renderAgents(await api("/api/agents"));
      pollWhileRunning();
    } finally {
      $("btn-query").disabled = false;
    }
  }));

  // --- tryb ciągły -----------------------------------------------------------------------
  function stopTimers() {
    state.timers.forEach(clearInterval);
    state.timers = [];
  }

  function setLive(on) {
    state.live = on;
    $("btn-start").disabled = on;
    $("btn-stop").disabled = !on;
    const badge = $("live-badge");
    badge.dataset.on = String(on);
    badge.textContent = on ? "tryb ciągły" : "tryb ręczny";
    stopTimers();
    if (on && document.visibilityState === "visible") {
      state.timers.push(setInterval(() => guarded(async () => {
        const live = await api("/api/live/heartbeat", "POST");
        if (!live.enabled) setLive(false);
      }), HEARTBEAT_MS));
      state.timers.push(setInterval(() => guarded(async () => {
        const [s, p] = await Promise.all([api("/api/servers"), api("/api/projects")]);
        renderServers(s);
        renderProjects(p);
        $("updated").textContent = `Odświeżono ${fmtTime(new Date().toISOString())}`;
      }), POLL_LIVE_MS));
      state.timers.push(setInterval(() => guarded(async () => renderAgents(await api("/api/agents"))),
        AGENTS_LIVE_MS));
    }
  }

  $("btn-start").addEventListener("click", () => guarded(async () => {
    const live = await api("/api/live/start", "POST");
    setLive(live.enabled);
    pollWhileRunning();
  }));

  $("btn-stop").addEventListener("click", () => guarded(async () => {
    const live = await api("/api/live/stop", "POST");
    setLive(live.enabled);
  }));

  // Karta niewidoczna (zamknięta aplikacja, wygaszony ekran) — bez heartbeatu; serwer sam wyłączy tryb.
  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState !== "visible") { stopTimers(); return; }
    if ($("app").hidden) return;
    guarded(async () => {
      const live = await api("/api/live");
      await refreshAll();
      setLive(live.enabled);
    });
  });

  // --- PWA -------------------------------------------------------------------------------
  if ("serviceWorker" in navigator) {
    navigator.serviceWorker.register("/sw.js", { scope: "/" }).catch(() => { /* np. http bez localhost */ });
  }

  // --- start -----------------------------------------------------------------------------
  (async () => {
    try {
      const session = await api("/api/session");
      if (session.authenticated) await showApp();
      else showLogin();
    } catch (e) {
      showLogin(e instanceof AuthError ? "" : e.message);
    }
  })();
})();
