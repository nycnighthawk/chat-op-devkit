/* Drives the standalone mock UI in a real browser: node mock/browser.test.js <path-to-html>
 * Needs `playwright` (resolvable from NODE_PATH) and a Chrome/Chromium binary in CHROME. Skipped by the pytest wrapper otherwise. */
"use strict";
const assert = require("assert");
const { chromium } = require("playwright");
const file = process.argv[2];
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--no-sandbox"] });
  const pg = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const errs = [];
  pg.on("pageerror", (e) => errs.push(String(e)));
  await pg.goto("file://" + file);
  await pg.selectOption("#speed", "0.4");

  // hub: the cross-project inbox and the three project cards, those needing the human first
  assert.equal(await pg.locator("#hub .pcard").count(), 3);
  assert.equal(await pg.locator("#hub .pcard").first().getAttribute("data-open"), "notes-api");
  assert.equal(await pg.locator("#hub .pcard").last().getAttribute("data-open"), "docs-site");
  assert((await pg.locator("#hub .inbox .row").count()) >= 3);

  await pg.click('.pcard[data-open="notes-api"]');
  const f = pg.frameLocator("#app");
  await f.locator(".chat.st-send").waitFor();
  assert.match(await f.locator("#heroTitle").innerText(), /2 chats need you/);
  assert.match(await f.locator(".col.you h3").innerText(), /Your move\s+2/);
  assert.match(await f.locator(".col:not(.you) h3").innerText(), /Waiting for the LLM\s+1/);
  assert(await f.locator('.chat[data-chat="c2"] .t').count());            // the clock of the packet pasted minutes ago

  // copy -> paste step -> "I pasted it" flag -> waiting with a clock
  await f.locator('.chat[data-chat="c4"] button[data-act="accept"]').click();
  await f.locator('.chat[data-chat="c3"] button[data-act="packet"]').click();
  await f.locator('.chat[data-chat="c3"].st-paste').waitFor();
  assert.match(await f.locator("#btnNextUp").innerText(), /I pasted it \(c3\)/);
  await f.locator("body").press("n");                                       // keyboard: N does the top action
  await f.locator('.chat[data-chat="c3"].st-waiting').waitFor();

  // a reply pasted ANYWHERE on the page (no textarea focused) is routed by its header
  await pg.waitForFunction(() => document.querySelector("#st-notes_api_c2").textContent === "reply ready", null, { timeout: 20000 });
  await pg.click("#cr-notes_api_c2");
  const reply = await pg.evaluate(() => window.shellClip());
  await f.locator("body").evaluate((body, text) => {
    const dt = new DataTransfer(); dt.setData("text", text);
    body.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }, reply);
  await f.locator('.chat[data-chat="c2"].st-closed').waitFor({ state: "attached", timeout: 15000 });
  assert.match(await f.locator("#progtxt").innerText(), /2 of 6 issues closed/);

  // back to the hub through the breadcrumb of the real page; the hub shows the new progress
  await f.locator("#crumb").click();
  await pg.locator("#hub .pcard").first().waitFor();
  assert.match(await pg.locator('.pcard[data-open="notes-api"]').innerText(), /2 of 6 issues closed/);
  assert.deepEqual(errs, []);
  await browser.close();
  console.log("mock browser ok");
})().catch((e) => { console.error(e); process.exit(1); });
