/* One optional, exact-origin permission; no cookie access or remote debugging. */
"use strict";
let lease = null, pending = false, ready = false;
const patterns = browser.runtime.getManifest().optional_permissions || [];
const pattern = patterns.length === 1 && /^https:\/\/[a-z0-9][a-z0-9.-]+[a-z0-9]\/\*$/.test(patterns[0]) ? patterns[0] : null;
const origin = pattern ? new URL(pattern.slice(0, -1)).origin : null;
async function clearPermission() {
  ready = false;
  if (!pattern) return;
  try {
    if (await browser.permissions.contains({origins: [pattern]}))
      await browser.permissions.remove({origins: [pattern]});
    ready = !(await browser.permissions.contains({origins: [pattern]}));
  } catch (_) { ready = false; }
}
clearPermission();
function revoke() {
  const old = lease;
  lease = null;
  if (old) {
    clearTimeout(old.timer);
    try { old.port.disconnect(); } catch (_) {}
    browser.browserAction.setBadgeText({tabId: old.tabId, text: ""}).catch(() => {});
  }
  clearPermission();
}
function denied(state = "denied") { return {ok: false, state}; }
function permitted(url, origin) {
  try {
    const u = new URL(url);
    return u.origin === origin && !u.username && !u.password &&
      (u.pathname === "/" || u.pathname === "/rfid" ||
       /^\/chargers\/[^/]+\/[^/]+$/.test(u.pathname));
  } catch (_) { return false; }
}
browser.browserAction.onClicked.addListener(async tab => {
  if (lease) { revoke(); return; }
  if (!ready || pending || !tab.active || !permitted(tab.url, origin)) return;
  pending = true;
  let port;
  try {
    // Called directly in the toolbar user gesture. A refusal is final.
    if (!(await browser.permissions.request({origins: [pattern]}))) return;
    ready = false;
    const live = await browser.tabs.get(tab.id);
    if (!live.active || !permitted(live.url, origin)) { await clearPermission(); return; }
    port = browser.runtime.connectNative("com.arthexis.gway_browser");
  } catch (_) { await clearPermission(); return; }
  finally { pending = false; }
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), x =>
    x.toString(16).padStart(2, "0")).join("");
  const current = {port, tabId: tab.id, url: tab.url, origin: null, bridgeReady: false, busy: false, timer: null, id};
  lease = current;
  function failBridge() {
    if (lease !== current) return;
    revoke();
    browser.browserAction.setBadgeText({tabId: tab.id, text: "ERR"}).catch(() => {});
  }
  browser.browserAction.setBadgeText({tabId: tab.id, text: "WAIT"}).catch(failBridge);
  current.timer = setTimeout(failBridge, 10000);
  port.onDisconnect.addListener(() => {
    if (lease === current) {
      if (current.bridgeReady) revoke(); else failBridge();
    }
  });
  port.onMessage.addListener(async request => {
    if (lease !== current) return;
    if (!current.origin) {
      if (typeof request.origin !== "string" || request.lease_seconds !== 600 ||
          request.origin !== origin || !permitted(current.url, request.origin)) { revoke(); return; }
      current.origin = request.origin;
      try { port.postMessage({consent: true}); } catch (_) { failBridge(); }
      return;
    }
    if (!current.bridgeReady) {
      if (request.bridge_ready !== true || Object.keys(request).length !== 1) { failBridge(); return; }
      current.bridgeReady = true;
      clearTimeout(current.timer);
      current.timer = setTimeout(revoke, 600000);
      browser.browserAction.setBadgeText({tabId: tab.id, text: "ON"}).catch(revoke);
      return;
    }
    if (current.busy) { revoke(); return; }
    current.busy = true;
    try {
      const live = await browser.tabs.get(current.tabId);
      const allowed = await browser.permissions.contains({origins: [pattern]});
      if (lease !== current) return;
      if (!live.active || !permitted(live.url, current.origin) || !allowed) {
        port.postMessage(denied()); revoke(); return;
      }
      if (live.status === "loading") { port.postMessage(denied("loading")); return; }
      if (request.operation === "status") {
        port.postMessage({ok: true, state: "ready"});
      } else {
        await browser.tabs.executeScript(current.tabId, {file: "reports.js", frameId: 0});
        if (lease !== current) return;
        const result = await browser.tabs.sendMessage(current.tabId,
          {origin: current.origin, lease: current.id, request}, {frameId: 0});
        if (lease === current) port.postMessage(result);
      }
    } catch (_) {
      if (lease === current) { try { port.postMessage(denied("unavailable")); } catch (_) {} revoke(); }
    } finally { current.busy = false; }
  });
});
browser.tabs.onRemoved.addListener(id => { if (lease && lease.tabId === id) revoke(); });
browser.tabs.onActivated.addListener(info => { if (lease && lease.tabId !== info.tabId) revoke(); });
browser.tabs.onUpdated.addListener((id, change) => {
  if (lease && lease.origin && id === lease.tabId && change.url && !permitted(change.url, lease.origin)) revoke();
});

browser.permissions.onRemoved.addListener(removed => {
  if (lease && removed.origins && removed.origins.includes(pattern)) revoke();
});
