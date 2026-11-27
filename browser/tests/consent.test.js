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
  let disconnected = false, injections = 0;
  const tab = {id: 4, active: true, url: "https://reports.example.test/"};
  const port = {onMessage: event(), onDisconnect: event(), postMessage(v) { messages.push(v); },
    disconnect() { disconnected = true; }};
  const browser = {
    browserAction: {onClicked: event(), setBadgeText: async () => {}},
    runtime: {connectNative(name) { assert.equal(name, "com.arthexis.gway_browser"); return port; }},
    tabs: {onRemoved: event(), onActivated: event(), onUpdated: event(),
      get: async () => tab, executeScript: async (_, options) => { injections++; assert.equal(options.file, "reports.js"); },
      sendMessage: async () => ({ok: true, state: "ready"})}
  };
  const context = {browser, URL, setTimeout: () => 1, clearTimeout: () => {}};
  vm.runInNewContext(fs.readFileSync(path.join(root, "background.js"), "utf8"), context);
  assert.equal(messages.length, 0);
  browser.browserAction.onClicked.fire(tab);
  await port.onMessage.fire({origin: "https://reports.example.test", lease_seconds: 600});
  assert.equal(messages[0].consent, true);
  await port.onMessage.fire({operation: "status"});
  assert.equal(messages[1].state, "ready");
  await port.onMessage.fire({operation: "snapshot"});
  assert.equal(injections, 1);
  browser.tabs.onActivated.fire({tabId: 99});
  assert.equal(disconnected, true);
  await port.onMessage.fire({operation: "snapshot"});
  assert.equal(injections, 1);
  browser.browserAction.onClicked.fire(tab);
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
  assert.equal((await listener.fire({origin: "https://different.example.test", request: {operation: "snapshot"}})).state, "denied");
  assert.equal((await listener.fire({origin: isolated.location.origin, request: {operation: "snapshot"}})).state, "denied");
}
main().catch(err => { console.error(err); process.exitCode = 1; });
