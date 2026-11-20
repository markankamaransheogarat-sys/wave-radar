"""Built-in local Web Dashboard (`http://127.0.0.1:8787`) for 1-click Drips actions."""

from __future__ import annotations

from aiohttp import web

from wave_radar.service import WaveRadarService

DASHBOARD_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Wave Radar — Live Drips Sniper</title>
  <style>
    :root {
      --bg: #0b0f14; --panel: #121922; --border: #1e2a38;
      --text: #e6edf3; --muted: #8b9bb0; --accent: #38bdf8;
      --hot: #f97316; --ok: #22c55e; --warn: #eab308; --bad: #ef4444;
    }
    * { box-sizing: border-box; }
    body { margin: 0; font-family: ui-sans-serif, system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); }
    header { display: flex; flex-wrap: wrap; gap: 12px; align-items: center; justify-content: space-between; padding: 14px 20px; border-bottom: 1px solid var(--border); background: #0e141c; }
    h1 { margin: 0; font-size: 18px; letter-spacing: 0.3px; }
    .stats { display: flex; gap: 10px; flex-wrap: wrap; align-items: center; }
    .pill { padding: 5px 10px; border-radius: 999px; font-size: 12px; font-weight: 600; background: var(--panel); border: 1px solid var(--border); }
    .pill.hot { border-color: var(--hot); color: #fdba74; }
    .pill.ok { border-color: var(--ok); color: #86efac; }
    .pill.warn { border-color: var(--bad); color: #fca5a5; }
    button { cursor: pointer; border: 1px solid var(--border); background: #182230; color: var(--text); padding: 6px 12px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    button:hover { border-color: var(--accent); }
    button.primary { background: #0369a1; border-color: #0284c7; }
    main { display: grid; grid-template-columns: 1.35fr 1fr; gap: 16px; padding: 16px 20px; max-width: 1500px; margin: 0 auto; }
    @media (max-width: 980px) { main { grid-template-columns: 1fr; } }
    .panel { background: var(--panel); border: 1px solid var(--border); border-radius: 10px; padding: 14px; }
    .panel h2 { margin: 0 0 12px 0; font-size: 15px; color: var(--accent); display: flex; justify-content: space-between; }
    .card { border: 1px solid var(--border); background: #0d131b; border-radius: 8px; padding: 12px; margin-bottom: 10px; }
    .card-head { display: flex; justify-content: space-between; gap: 8px; align-items: center; margin-bottom: 8px; }
    .repo { font-weight: 700; font-size: 14px; color: #fff; }
    .badge { font-size: 11px; padding: 2px 8px; border-radius: 6px; font-weight: 600; }
    .b-hot { background: rgba(249,115,22,0.18); color: #fb923c; }
    .b-solo { background: rgba(56,189,248,0.15); color: #7dd3fc; }
    .b-comp { background: rgba(234,179,8,0.15); color: #fde047; }
    .b-stale { background: rgba(239,68,68,0.18); color: #fca5a5; }
    .b-ass { background: rgba(34,197,94,0.2); color: #86efac; }
    .cand { border-top: 1px solid var(--border); padding-top: 8px; margin-top: 8px; }
    .cand-title { font-size: 13px; font-weight: 600; margin-bottom: 6px; }
    pre { white-space: pre-wrap; word-break: break-word; background: #080c11; border: 1px solid #19222d; padding: 8px; border-radius: 6px; font-size: 12px; color: #cbd5e1; margin: 6px 0; }
    .actions { display: flex; gap: 8px; flex-wrap: wrap; }
    a.btn { display: inline-block; text-decoration: none; background: #1d4ed8; color: #fff; padding: 6px 10px; border-radius: 6px; font-size: 12px; font-weight: 600; }
    a.btn:hover { background: #2563eb; }
    .slot-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; padding: 8px 0; border-bottom: 1px solid var(--border); font-size: 13px; }
    .slot-row:last-child { border-bottom: none; }
    .muted { color: var(--muted); font-size: 12px; }
  </style>
</head>
<body>
  <header>
    <div>
      <h1>⚡ Wave Radar — Stellar Wave Live Sniper</h1>
      <div class="muted" id="meta">Waiting for first scan...</div>
    </div>
    <div class="stats">
      <span class="pill" id="stat-slots">Slots: -/15</span>
      <span class="pill ok" id="stat-assigned">Assigned: -</span>
      <span class="pill warn" id="stat-stale">Stale: -</span>
      <button id="btn-sound">🔔 Sound: OFF</button>
      <button class="primary" id="btn-scan">↻ Scan Now</button>
    </div>
  </header>
  <main>
    <section class="panel">
      <h2><span>🔥 Online Maintainers &amp; 0-App 200-pt Candidates</span><span class="muted" id="hot-count"></span></h2>
      <div id="hot-list"><div class="muted">Scanning...</div></div>
    </section>
    <section class="panel">
      <h2><span>📋 Your Wave Queue &amp; Events</span><span class="muted" id="apps-count"></span></h2>
      <div id="apps-list"></div>
      <h2 style="margin-top:16px;"><span>📡 Activity Feed</span></h2>
      <div id="events-list"></div>
    </section>
  </main>
  <script>
    let soundOn = false;
    let lastHotSignature = "";
    const btnSound = document.getElementById("btn-sound");
    btnSound.onclick = () => {
      soundOn = !soundOn;
      btnSound.textContent = soundOn ? "🔔 Sound: ON" : "🔔 Sound: OFF";
    };
    function beep() {
      if (!soundOn) return;
      try {
        const ctx = new (window.AudioContext || window.webkitAudioContext)();
        const osc = ctx.createOscillator();
        osc.type = "sine"; osc.frequency.value = 880;
        osc.connect(ctx.destination); osc.start();
        setTimeout(() => { osc.stop(); ctx.close(); }, 180);
      } catch (_) {}
    }
    function esc(s) {
      return String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
    }
    async function copyText(btn, text) {
      await navigator.clipboard.writeText(text);
      const old = btn.textContent; btn.textContent = "✓ Copied!";
      setTimeout(() => btn.textContent = old, 1400);
    }
    function badgeFor(state) {
      if (state === "assigned" || state === "pr_open") return `<span class="badge b-ass">${state}</span>`;
      if (state === "stale") return `<span class="badge b-stale">STALE - withdraw?</span>`;
      if (state === "applied_solo") return `<span class="badge b-solo">solo (1 app)</span>`;
      if (state === "applied_competed") return `<span class="badge b-comp">competed</span>`;
      return `<span class="badge">${esc(state)}</span>`;
    }
    function render(data) {
      document.getElementById("meta").textContent = `User: ${data.username} | Updated: ${new Date(data.generated_at).toLocaleTimeString()} | Window: ${data.online_window_minutes}m`;
      document.getElementById("stat-slots").textContent = `Slots: ${data.active_slots_count}/15 (solo ${data.solo_slots_count})`;
      document.getElementById("stat-assigned").textContent = `Assigned/PR: ${data.assigned_count}`;
      document.getElementById("stat-stale").textContent = `Stale: ${data.stale_slots_count}`;
      const hotEl = document.getElementById("hot-list");
      const withCands = (data.hot_maintainers || []).filter(m => m.candidates && m.candidates.length > 0);
      document.getElementById("hot-count").textContent = `${data.hot_maintainers.length} active repo(s)`;
      const sig = withCands.map(m => m.repo + ":" + m.candidates.map(c => c.issue_number).join(",")).join("|");
      if (sig && sig !== lastHotSignature && lastHotSignature !== "") beep();
      lastHotSignature = sig;
      if (!data.hot_maintainers.length) {
        hotEl.innerHTML = `<div class="muted">No maintainers assigned issues in the last ${data.online_window_minutes} min. Auto-refreshing...</div>`;
      } else {
        hotEl.innerHTML = data.hot_maintainers.map(m => `
          <div class="card">
            <div class="card-head">
              <span class="repo">${esc(m.repo)}</span>
              <span class="badge b-hot">${m.assigned_recently}x assigned (#${m.latest_issue_number} → ${esc(m.latest_assignee)})</span>
            </div>
            ${m.candidates.length ? m.candidates.map((c, idx) => `
              <div class="cand">
                <div class="cand-title">#${c.issue_number} — ${esc(c.title)} <span class="muted">(${c.points} pts | ${c.pending_apps} apps)</span></div>
                <pre id="pitch-${esc(m.repo)}-${c.issue_number}">${esc(c.pitch)}</pre>
                <div class="actions">
                  <a class="btn" target="_blank" rel="noopener" href="${esc(c.drips_url)}">Open Drips ↗</a>
                  <a class="btn" style="background:#334155" target="_blank" rel="noopener" href="${esc(c.github_url)}">GitHub ↗</a>
                  <button onclick='copyText(this, ${JSON.stringify(c.pitch)})'>📋 Copy Pitch</button>
                </div>
              </div>
            `).join("") : `<div class="muted">No 0-app ${200}-pt candidates left in this repo right now.</div>`}
          </div>
        `).join("");
      }
      const apps = (data.applications || []).filter(a => a.state !== "lost");
      document.getElementById("apps-count").textContent = `${apps.length} active/assigned`;
      document.getElementById("apps-list").innerHTML = apps.map(a => `
        <div class="slot-row">
          <div>
            <a style="color:#e6edf3;text-decoration:none;font-weight:600" target="_blank" href="${esc(a.url)}">${esc(a.repo)}#${a.issue_number}</a>
            <div class="muted">${esc(a.title)} · ${a.age_hours}h ago · ${a.applicants_count} app(s)</div>
          </div>
          ${badgeFor(a.state)}
        </div>
      `).join("") || `<div class="muted">No tracked active applications.</div>`;
      document.getElementById("events-list").innerHTML = (data.events || []).slice(0, 10).map(ev => `
        <div class="slot-row"><span>${esc(ev.message)}</span><span class="muted">${new Date(ev.timestamp).toLocaleTimeString()}</span></div>
      `).join("") || `<div class="muted">No events yet.</div>`;
    }
    async function refresh() {
      try {
        const res = await fetch("/api/snapshot");
        if (res.ok) render(await res.json());
      } catch (_) {}
    }
    document.getElementById("btn-scan").onclick = async () => {
      const btn = document.getElementById("btn-scan");
      btn.textContent = "Scanning...";
      try {
        const res = await fetch("/api/scan", { method: "POST" });
        if (res.ok) render(await res.json());
      } finally { btn.textContent = "↻ Scan Now"; }
    };
    refresh();
    setInterval(refresh, 15000);
  </script>
</body>
</html>
"""


def create_web_app(service: WaveRadarService) -> web.Application:
    """Create the aiohttp web application exposing dashboard UI and JSON endpoints."""
    app = web.Application()

    async def index(_request: web.Request) -> web.Response:
        return web.Response(text=DASHBOARD_HTML, content_type="text/html")

    async def get_snapshot(_request: web.Request) -> web.Response:
        snap = service.latest_snapshot
        if snap is None:
            snap = await service.scan_once()
        return web.json_response(snap.to_dict())

    async def trigger_scan(_request: web.Request) -> web.Response:
        snap = await service.scan_once()
        return web.json_response(snap.to_dict())

    app.router.add_get("/", index)
    app.router.add_get("/api/snapshot", get_snapshot)
    app.router.add_post("/api/scan", trigger_scan)
    return app
