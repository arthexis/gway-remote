/* Hermetic extension consent/route and semantic action fixtures. */
"use strict";
const assert = require("node:assert/strict");
const vm = require("node:vm");
const fs = require("node:fs");
const path = require("node:path");
const root = path.join(__dirname, "../firefox");
function event() { return {addListener(fn) { this.fire = fn; }}; }
async function main() {
  const messages = [], badges = [];
  let disconnected = false, injections = 0, granted = false, allow = true;
  const tab = {id: 4, active: true, url: "https://reports.example.test/"};
  const port = {onMessage: event(), onDisconnect: event(), postMessage(v) { messages.push(v); },
    disconnect() { disconnected = true; }};
  const browser = {
    browserAction: {onClicked: event(), setBadgeText: async ({text}) => { badges.push(text); }},
    permissions: {onRemoved: event(), contains: async () => granted, remove: async () => { granted = false; return true; }, request: async ({origins}) => { assert.equal(origins[0], "https://reports.example.test/*"); granted = allow; return allow; }},
    runtime: {getManifest: () => ({optional_permissions: ["https://reports.example.test/*"]}), connectNative(name) { assert.equal(name, "com.arthexis.gway_browser"); return port; }},
    tabs: {onRemoved: event(), onActivated: event(), onUpdated: event(),
      get: async () => tab, executeScript: async (_, options) => { injections++; assert.equal(options.file, "/reports.js"); assert.equal(options.frameId, 0); },
      sendMessage: async () => ({ok: true, state: "ready"})}
  };
  const warnings = [];
  const context = {browser, URL, console: {warn: (...args) => warnings.push(args)}, crypto: require("node:crypto").webcrypto, setTimeout: () => 1, clearTimeout: () => {}};
  vm.runInNewContext(fs.readFileSync(path.join(root, "background.js"), "utf8"), context);
  assert.equal(messages.length, 0);
  await new Promise(resolve => setImmediate(resolve));
  await browser.browserAction.onClicked.fire(tab);
  await port.onMessage.fire({origin: "https://reports.example.test", lease_seconds: 600});
  assert.equal(messages[0].consent, true);
  assert.equal(badges.at(-1), "WAIT");
  assert.ok(!badges.includes("ON"));
  await port.onMessage.fire({bridge_ready: true});
  assert.equal(badges.at(-1), "ON");
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
  await new Promise(resolve => setImmediate(resolve));
  allow = false;
  await browser.browserAction.onClicked.fire(tab);
  assert.equal(granted, false);
  assert.equal(messages.length, 3);
  allow = true;
  await browser.browserAction.onClicked.fire(tab);
  await port.onMessage.fire({origin: "https://reports.example.test", lease_seconds: 600});
  assert.equal(granted, true);
  await port.onMessage.fire({bridge_ready: true});
  let resolveInjection, sent = 0;
  browser.tabs.executeScript = async () => new Promise(resolve => { resolveInjection = resolve; });
  browser.tabs.sendMessage = async () => { sent++; return {ok:true,state:"ready"}; };
  const inFlight = port.onMessage.fire({operation: "click", ref: "a".repeat(32)});
  await new Promise(resolve => setImmediate(resolve));
  browser.tabs.onActivated.fire({tabId: 99});
  resolveInjection();
  await inFlight;
  assert.equal(sent, 0);
  // Consent without readiness must not show ON or execute an action.
  await new Promise(resolve => setImmediate(resolve));
  await browser.browserAction.onClicked.fire(tab);
  await port.onMessage.fire({origin: "https://reports.example.test", lease_seconds: 600});
  assert.equal(badges.at(-1), "WAIT");
  await port.onMessage.fire({operation: "snapshot"});
  assert.equal(badges.at(-1), "ERR");
  await new Promise(resolve => setImmediate(resolve));
  assert.equal(granted, false);
  assert.equal(sent, 0);
  // Fail each dispatch stage without leaking exception details or retaining consent.
  const originalGet = browser.tabs.get, originalContains = browser.permissions.contains;
  const validInjection = async (_, options) => {
    assert.equal(options.file, "/reports.js"); assert.equal(options.frameId, 0);
  };
  const validMessage = async () => ({ok: true, state: "ready"});
  const fail = async () => { throw new Error("private fixture data"); };
  for (const stage of ["tab_recheck_failed", "permission_recheck_failed", "script_injection_failed",
      "adapter_message_failed", "adapter_response_invalid", "adapter_execution_failed", "response_post_failed"]) {
    browser.tabs.get = originalGet; browser.permissions.contains = originalContains;
    browser.tabs.executeScript = validInjection; browser.tabs.sendMessage = validMessage;
    port.postMessage = v => messages.push(v);
    await new Promise(resolve => setImmediate(resolve));
    await browser.browserAction.onClicked.fire(tab);
    await port.onMessage.fire({origin: "https://reports.example.test", lease_seconds: 600});
    await port.onMessage.fire({bridge_ready: true});
    assert.equal(badges.at(-1), "ON");
    if (stage === "tab_recheck_failed") browser.tabs.get = fail;
    if (stage === "permission_recheck_failed") {
      let once = true;
      browser.permissions.contains = async () => { if (once) { once = false; return fail(); } return granted; };
    }
    if (stage === "script_injection_failed") browser.tabs.executeScript = fail;
    if (stage === "adapter_message_failed") browser.tabs.sendMessage = fail;
    if (stage === "adapter_response_invalid") browser.tabs.sendMessage = async () => undefined;
    if (stage === "adapter_execution_failed") browser.tabs.sendMessage = async () => ({ok:false,state:stage});
    if (stage === "response_post_failed") {
      let once = true;
      port.postMessage = v => { if (once) { once = false; throw new Error("private fixture data"); } messages.push(v); };
    }
    await port.onMessage.fire({operation: "snapshot"});
    assert.equal(messages.at(-1).state, stage);
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(granted, false);
    assert.equal(badges.at(-1), "");
  }
  assert.ok(!JSON.stringify({messages,warnings}).includes("private fixture data"));
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
  dom.querySelector = () => { throw new Error("private adapter fixture"); };
  assert.equal((await invoke({operation: "snapshot"})).state, "adapter_execution_failed");
  assert.ok(!JSON.stringify(await invoke({operation: "snapshot"})).includes("private adapter fixture"));
}
main().catch(err => { console.error(err); process.exitCode = 1; });
