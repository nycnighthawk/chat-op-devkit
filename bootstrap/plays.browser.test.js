/* Drives the bootstrap plays page in a real browser: node bootstrap/plays.browser.test.js <path-to-html>
 * Needs `playwright` (NODE_PATH) and a Chrome in CHROME. Skipped by the pytest wrapper otherwise. */
"use strict";
const assert = require("assert");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { chromium } = require("playwright");
const file = process.argv[2];
(async () => {
  const browser = await chromium.launch({ executablePath: process.env.CHROME || undefined, args: ["--no-sandbox"] });
  const ctx = await browser.newContext({ acceptDownloads: true, viewport: { width: 1360, height: 900 } });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"]).catch(() => {});
  const pg = await ctx.newPage();
  const errs = [];
  pg.on("pageerror", (e) => errs.push(String(e)));
  pg.on("console", (m) => { if (m.type() === "error") errs.push(m.text()); });
  await pg.goto("file://" + file);

  // structure: six acts, seeded path by default (purist-only plays hidden)
  assert.equal(await pg.locator("h2.act[id^=act]").count(), 6);
  assert.equal(await pg.locator("#p-1\\.1").count(), 1);
  assert.equal(await pg.locator("#p-1\\.1p").count(), 0);
  await pg.click("#m-purist");
  assert.equal(await pg.locator("#p-1\\.1p").count(), 1);
  assert.equal(await pg.locator("#p-1\\.1").count(), 0);
  await pg.click("#m-seeded");

  // every copy button has something to copy
  const empties = await pg.evaluate(() => [...document.querySelectorAll(".cmd pre")].filter((p) => !p.textContent.trim()).length);
  assert.equal(empties, 0);

  // done checkbox persists and updates progress
  await pg.check("#d-0\\.1");
  assert.match(await pg.locator("#prog").innerText(), /^1 of /);
  await pg.reload();
  assert.equal(await pg.isChecked("#d-0\\.1"), true);
  await pg.uncheck("#d-0\\.1");

  // board: only roots are ready; applying S1 unlocks S2, S3, S5 (not S4's dependents before S4)
  const ready = () => pg.locator(".sl.ready h4").allInnerTexts();
  assert.deepEqual((await ready()).map((t) => t.split(" ")[0]).sort(), ["S1", "S4"]);
  assert.match(await pg.locator(".next").innerText(), /open 2 chats at once/);
  const card = (id) => pg.locator(".sl", { has: pg.locator(`h4:text-matches("^${id} ")`) });
  for (const label of ["I ran pack", "I pasted it", "Reply copied", "Applied, all green"]) await card("S1").getByRole("button", { name: label }).click();
  assert.deepEqual((await ready()).map((t) => t.split(" ")[0]).sort(), ["S2", "S3", "S4", "S5"]);
  assert.equal(await card("S6").locator("button.pri").count(), 0);   // locked until S2..S5 are applied

  // the kit: a real zip with every file, readable by python's zipfile
  const [dl] = await Promise.all([pg.waitForEvent("download"), pg.click("#kitbtn")]);
  const out = path.join(os.tmpdir(), "plays-kit-" + process.pid + ".zip");
  await dl.saveAs(out);
  assert.equal(dl.suggestedFilename(), "chatop-bootstrap-kit.zip");
  const names = await pg.evaluate(() => window.__plays.kitFiles().map((f) => f.name));
  assert(names.includes("bootstrap/relay.py") && names.includes("pyproject.toml"));
  fs.writeFileSync(out + ".names", JSON.stringify(names));

  assert.deepEqual(errs, []);
  await browser.close();
  console.log("plays browser test ok; zip at " + out);
})().catch((e) => { console.error(e); process.exit(1); });
