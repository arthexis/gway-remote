/* Fixed, isolated-world Reports adapter; never reads inputs, cookies or storage. */
"use strict";
(() => {
  if (globalThis.gwayReportsAdapterInstalled) return;
  globalThis.gwayReportsAdapterInstalled = true;
  let refs = new Map();
  let snapshotAt = 0;
  const pageKind = path => path === "/" ? "dashboard" : path === "/rfid" ? "rfid" :
    /^\/chargers\/[^/]+\/[^/]+$/.test(path) ? "charger" : "other";
  const denied = (state = "denied") => ({ok: false, state});
  const visible = el => el && el.isConnected && el.getClientRects().length > 0 &&
    !el.closest("[hidden]") && getComputedStyle(el).visibility !== "hidden";
  const token = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), x =>
    x.toString(16).padStart(2, "0")).join("");
  const textIs = (el, text) => el && el.textContent.trim() === text;
  function hrefFor(el, kind) {
    if (!(el instanceof HTMLAnchorElement) || el.hasAttribute("download")) return null;
    const u = new URL(el.href);
    if (u.origin !== location.origin || u.username || u.password || u.hash) return null;
    if (kind === "charger_detail") {
      if (pageKind(u.pathname) !== "charger" || [...u.searchParams.keys()].some(k => k !== "tz")) return null;
    } else {
      if (u.pathname !== "/rfid" || [...u.searchParams.keys()].some(k => !["rfid","otros","tz","page"].includes(k))) return null;
      if ((u.searchParams.has("rfid") === u.searchParams.has("otros")) ||
          [...u.searchParams.keys()].some(k => u.searchParams.getAll(k).length !== 1)) return null;
      if (kind === "rfid_next" &&
          (u.searchParams.get("rfid") !== new URL(location.href).searchParams.get("rfid") ||
           u.searchParams.get("otros") !== new URL(location.href).searchParams.get("otros"))) return null;
    }
    return u.href;
  }
  function snapshot() {
    refs = new Map();
    snapshotAt = Date.now();
    const page = pageKind(location.pathname);
    const evidence = {};
    const controls = [];
    function add(kind, el, link = false) {
      if (controls.length >= 32 || !visible(el) || el.disabled) return;
      const href = link ? hrefFor(el, kind) : null;
      if (link && !href) return;
      const ref = token();
      refs.set(ref, {kind, el, href, page, url: location.href});
      controls.push({ref, kind});
    }
    if (page === "dashboard") {
      const panel = document.querySelector("#rfid-cards");
      if (!panel || !document.querySelector(".transactions-panel")) return denied();
      evidence.rfid_summary_rows = panel.querySelectorAll("tbody tr").length;
      evidence.session_rows = document.querySelectorAll(".transactions-panel tbody tr").length;
      evidence.operator_admin_hidden = !document.querySelector(".users-panel");
      for (const el of panel.querySelectorAll('tbody a[href]')) add("rfid_history", el, true);
      for (const el of document.querySelectorAll('.connectors-panel a[href^="/chargers/"]')) add("charger_detail", el, true);
    } else if (page === "rfid") {
      const table = document.querySelector('[aria-label="Sesiones de la tarjeta"] table');
      if (!table) return denied();
      evidence.session_rows = table.querySelectorAll("tbody tr").length;
      evidence.history_chart = visible(document.querySelector('svg[aria-label="Energía acumulada por sesión en kWh"]'));
      const nav = document.querySelector('nav[aria-label="Páginas de sesiones"]');
      const match = nav && nav.textContent.match(/Página\s+(\d+)\s+de\s+(\d+)/);
      if (match) { evidence.history_page = Number(match[1]); evidence.history_pages = Number(match[2]); }
      if (nav) add("rfid_next", nav.querySelector('a[rel="next"]'), true);
    } else if (page === "charger") {
      evidence.heartbeat_groups = 0;
      evidence.loaded_events = 0;
      evidence.response_id_header = false;
      evidence.soc_header = [...document.querySelectorAll("th")].some(el => /SoC/.test(el.textContent));
      for (const details of document.querySelectorAll("details.event-group")) {
        const summary = details.querySelector("summary");
        if (!textIs(summary, "Heartbeat")) continue;
        evidence.heartbeat_groups++;
        const holder = details.closest(".event-summary-row")?.nextElementSibling?.querySelector(".event-detail");
        if (!holder) continue;
        if (!details.open) add("heartbeat_expand", summary);
        else {
          evidence.loaded_events += holder.querySelectorAll("tbody tr").length;
          evidence.response_id_header ||= [...holder.querySelectorAll("th")].some(el => textIs(el, "ID respuesta"));
          for (const btn of holder.querySelectorAll('button[type="button"]')) {
            if (textIs(btn, "Ver 50 más")) add("heartbeat_next", btn);
          }
        }
      }
    } else return denied();
    return {ok: true, state: "ready", page, controls, evidence};
  }
  function click(ref) {
    const item = refs.get(ref);
    refs = new Map(); // single-use even on failure; caller must obtain fresh snapshot
    if (!item || Date.now() - snapshotAt > 30000 || item.url !== location.href ||
        !visible(item.el) || item.el.disabled || pageKind(location.pathname) !== item.page) return denied("stale");
    if (item.href) {
      if (hrefFor(item.el, item.kind) !== item.href) return denied("stale");
      // Navigate only through the reviewed same-origin link, not an arbitrary URL.
      setTimeout(() => { if (location.href === item.url && hrefFor(item.el, item.kind) === item.href) location.assign(item.href); }, 100);
      return {ok: true, state: "navigation_started"};
    }
    if (item.page !== "charger") return denied();
    const el = item.el;
    if (item.kind === "heartbeat_expand") {
      if (!el.matches("details.event-group > summary") || !textIs(el, "Heartbeat") || el.parentElement.open) return denied("stale");
    } else if (item.kind === "heartbeat_next") {
      if (!el.matches('.event-detail button[type="button"]') || !textIs(el, "Ver 50 más") || el.hidden) return denied("stale");
      const group = el.closest(".event-detail")?.closest("tr")?.previousElementSibling?.querySelector("details.event-group[open] > summary");
      if (!textIs(group, "Heartbeat")) return denied("stale");
    } else return denied();
    el.click();
    return {ok: true, state: "action_started"};
  }
  browser.runtime.onMessage.addListener(message => {
    if (window !== top || message.origin !== location.origin || document.querySelector('input[type="password"]')) return Promise.resolve(denied());
    const r = message.request;
    let result;
    if (r.operation === "snapshot") result = snapshot();
    else if (r.operation === "click") result = click(r.ref);
    else if (r.operation === "scenario_run") {
      const s = snapshot();
      if (!s.ok) result = s;
      else {
        const found = s.controls.filter(x => x.kind === r.scenario);
        // The operator must select explicitly if multiple controls match.
        result = found.length === 1 ? click(found[0].ref) : denied("ambiguous");
      }
    } else result = denied();
    return Promise.resolve(result);
  });
})();
