/* Hermetic extension consent/route and semantic action fixtures. */
"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "../firefox");
function event() { return {addListener(fn) { this.fire = fn; }}; }
async function main() {
  const messages = [];
  let disconnected = false, injections = 0, granted = false, allow = true;
  const tab = {id: 4, active: true, url: "https://reports.example.test/"};
  const port = {onMessage: event(), onDisconnect: event(), postMessage(v) { messages.push(v); },
    disconnect() { disconnected = true; }};
  const browser = {
    browserAction: {onClicked: event(), setBadgeText: async () => {}},
    permissions: {onRemoved: event(), contains: async () => granted, remove: async () => { granted = false; return true; }, request: async ({origins}) => { assert.equal(origins[0], "https://reports.example.test/*"); granted = allow; return allow; }},
    runtime: {getManifest: () => ({optional_permissions: ["https://reports.example.test/*"]}), connectNative(name) { assert.equal(name, "com.arthexis.gway_browser"); return port; }},
    tabs: {onRemoved: event(), onActivated: event(), onUpdated: event(),
      get: async () => tab, executeScript: async (_, options) => { injections++; assert.equal(options.file, "reports.js"); },
      sendMessage: async () => ({ok: true, state: "ready"})}
  };
  const context = {browser, URL, crypto: require("node:crypto").webcrypto, setTimeout: () => 1, clearTimeout: () => {}};
  vm.runInNewContext(fs.readFileSync(path.join(root, "background.js"), "utf8"), context);
  assert.equal(messages.length, 0);
  await new Promise(resolve => setImmediate(resolve));
  await browser.browserAction.onClicked.fire(tab);
  await port.onMessage.fire({origin: "https://reports.example.test", lease_seconds: 600});
  assert.equal(messages[0].consent, true);
  await port.onMessage.fire({operation: "status"});
  assert.equal(messages[1].state, "ready");
  await port.onMessage.fire({operation: "snapshot"});
  assert.equal(injections, 1);
  browser.tabs.onActivated.fire({tabId: 99});
  assert.equal(disconnected, true);
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(granted, false);
  await port.onMessage.fire({operation: "snapshot"});
  assert.equal(injections, 1);
  await new Promise(resolve => setImmediate(resolve));
  await browser.browserAction.onClicked.fire(tab);
  await port.onMessage.fire({origin: "https://different.example.test", lease_seconds: 600});
  assert.equal(messages.length, 3);
  assert.equal(injections, 1);
  // Adapter refuses login pages and unapproved origin without reading DOM.
  const listener = event();
  const doc = {querySelector(selector) { assert.equal(selector, 'input[type="password"]'); return {}; }};
  const isolated = {browser: {runtime: {onMessage: listener}}, document: doc,
    location: {origin: "https://reports.example.test"}, window: {}, top: null};
  isolated.top = isolated.window;
  vm.runInNewContext(fs.readFileSync(path.join(root, "reports.js"), "utf8"), isolated);
  assert.equal((await listener.fire({origin: "https://different.example.test", lease: "a".repeat(32), request: {operation: "snapshot"}})).state, "denied");
  assert.equal((await listener.fire({origin: isolated.location.origin, lease: "a".repeat(32), request: {operation: "snapshot"}})).state, "denied");
  // Synthetic dashboard adapter: no real customer data or browser.
  const listener2 = event();
  class Anchor {
    constructor(href) { this.href = href; this.isConnected = true; }
    hasAttribute() { return false; }
    getClientRects() { return [1]; }
    closest() { return null; }
  }
  const valid = new Anchor("https://reports.example.test/rfid?rfid=fixture&tz=UTC");
  const foreign = new Anchor("https://other.example.test/rfid?rfid=fixture");
  const wrongPath = new Anchor("https://reports.example.test/accounts");
  const invalidQuery = new Anchor("https://reports.example.test/rfid?rfid=fixture&unexpected=1");
  const panel = {querySelectorAll(sel) { return sel === "tbody tr" ? [1,2] : [valid,foreign,wrongPath,invalidQuery]; }};
  let navigated = null, now = 1000;
  const loc = {origin: "https://reports.example.test", pathname: "/", href: "https://reports.example.test/",
    assign(url) { navigated = url; }};
  const dom = {
    querySelector(sel) {
      if (sel === "#rfid-cards") return panel;
      if (sel === ".transactions-panel") return {};
      return null;
    },
    querySelectorAll(sel) { return sel === ".transactions-panel tbody tr" ? [1,2,3] : []; }
  };
  const ctx = {browser: {runtime: {onMessage: listener2}}, document: dom, location: loc,
    HTMLAnchorElement: Anchor, URL, window: {}, top: null,
    Date: {now: () => now}, crypto: require("node:crypto").webcrypto,
    getComputedStyle: () => ({visibility: "visible"}), setTimeout: fn => fn()};
  ctx.top = ctx.window;
  vm.runInNewContext(fs.readFileSync(path.join(root, "reports.js"), "utf8"), ctx);
  let lease = "a".repeat(32);
  const invoke = request => listener2.fire({origin: loc.origin, lease, request});
  let snap = await invoke({operation: "snapshot"});
  assert.equal(snap.controls.length, 1);
  assert.equal(snap.evidence.rfid_summary_rows, 2);
  assert.equal(snap.evidence.session_rows, 3);
  assert.equal(snap.controls[0].kind, "rfid_history");
  assert.ok(!JSON.stringify(snap).includes("fixture"));
  const ref = snap.controls[0].ref;
  assert.equal((await invoke({operation: "click", ref})).state, "navigation_started");
  assert.equal(navigated, valid.href);
  assert.equal((await invoke({operation: "click", ref})).state, "stale");
  snap = await invoke({operation: "snapshot"});
  now += 30001;
  assert.equal((await invoke({operation: "click", ref: snap.controls[0].ref})).state, "stale");
  snap = await invoke({operation: "snapshot"});
  lease = "b".repeat(32);
  assert.equal((await invoke({operation: "click", ref: snap.controls[0].ref})).state, "stale");
  snap = await invoke({operation: "snapshot"});
  valid.href = "https://other.example.test/rfid?rfid=fixture";
  assert.equal((await invoke({operation: "click", ref: snap.controls[0].ref})).state, "stale");
  assert.equal((await invoke({operation: "evaluate"})).state, "denied");
}
main().catch(err => { console.error(err); process.exitCode = 1; });
