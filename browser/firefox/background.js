/* No host permissions, cookie access, remote debugging or arbitrary scripts. */
"use strict";
let lease = null;
function revoke() {
  const old = lease;
  lease = null;
  if (old) {
    clearTimeout(old.timer);
    try { old.port.disconnect(); } catch (_) {}
    browser.browserAction.setBadgeText({tabId: old.tabId, text: ""}).catch(() => {});
  }
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
browser.browserAction.onClicked.addListener(tab => {
  if (lease) { revoke(); return; }
  if (!tab.active || !tab.url || !tab.url.startsWith("https://")) return;
  const port = browser.runtime.connectNative("com.arthexis.gway_browser");
  const id = Array.from(crypto.getRandomValues(new Uint8Array(16)), x =>
    x.toString(16).padStart(2, "0")).join("");
  const current = {port, tabId: tab.id, url: tab.url, origin: null, busy: false, timer: null, id};
  lease = current;
  current.timer = setTimeout(revoke, 10000);
  port.onDisconnect.addListener(() => { if (lease === current) revoke(); });
  port.onMessage.addListener(async request => {
    if (lease !== current) return;
    if (!current.origin) {
      if (typeof request.origin !== "string" || request.lease_seconds !== 600 ||
          !permitted(current.url, request.origin)) { revoke(); return; }
      current.origin = request.origin;
      clearTimeout(current.timer);
      current.timer = setTimeout(revoke, 600000);
      port.postMessage({consent: true});
      browser.browserAction.setBadgeText({tabId: tab.id, text: "ON"}).catch(revoke);
      return;
    }
    if (current.busy) { revoke(); return; }
    current.busy = true;
    try {
      const live = await browser.tabs.get(current.tabId);
      if (!live.active || !permitted(live.url, current.origin)) {
        port.postMessage(denied()); revoke(); return;
      }
      if (request.operation === "status") {
        port.postMessage({ok: true, state: "ready"});
      } else {
        await browser.tabs.executeScript(current.tabId, {file: "reports.js", frameId: 0});
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
