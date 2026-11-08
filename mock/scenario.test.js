/* Runs the whole lab-5 scenario against the mock backend with node: node mock/scenario.test.js */
"use strict";
require("./backend.js");
const assert = require("assert");
const M = globalThis.MOCK;
M.setApplyDelay(0);
const api = (p, b) => M.api(p, b);
const settle = async () => { await M.idle(); await new Promise((r) => setTimeout(r, 5)); await M.idle(); };
const chatOf = async (id) => (await api("board")).chats.find((c) => c.id === id);
const paste = async (text) => { const r = await api("paste", { text }); await settle(); return r; };
const relay = async (chat) => { const p = await api("packet", { chat }); return { p, reply: M.llmReply(p.text) }; };

(async () => {
  let s = await api("status");
  assert.equal(s.phase, "plan"); assert.deepEqual(s.chats, []);
  await assert.rejects(() => api("next", {}), /approve/);
  await api("approve", {});
  let b = await api("board");
  assert.deepEqual(b.chats.map((c) => [c.id, c.issue, c.status]), [["c1", "S0", "queued"]]);

  // S0 in c1, then S1 and S2 open two chats at once
  let { p, reply } = await relay("c1");
  assert.equal(p.kind, "full"); assert(reply.includes("<<<CHATOP chat=c1 turn=1>>>"));
  await paste(reply);
  b = await api("board");
  assert.deepEqual(b.chats.map((c) => [c.id, c.issue, c.status]), [["c1", null, "done"], ["c2", "S1", "queued"], ["c3", "S2", "queued"]]);
  const r2 = await relay("c2"), r3 = await relay("c3");
  assert(r2.p.kind === "full" && r3.p.kind === "full");

  // out of order: c3 (syntax errors) answers first -> ONE rejection with both errors; then c2 fails its test
  let r = await paste(r3.reply);
  assert.equal((await api("job", { id: r.job })).result.errors.length, 2);
  assert((await chatOf("c3")).repair.includes("chat=c3 turn=1"));
  await paste(r2.reply);
  assert.equal((await chatOf("c2")).status, "ready"); assert((await chatOf("c2")).evidence.includes("AssertionError"));

  // c3 repairs (isolated from c2's failing test) and finishes
  const fix3 = M.llmReply(r3.p.text);
  assert(fix3.includes("outcome=pass"));
  await paste(fix3);
  assert.equal((await chatOf("c3")).status, "done");
  assert(M.flags().isolated && M.flags().outOfOrder && M.flags().batchReject);

  // c2 continues with a DELTA packet carrying the failure
  const d2 = await api("packet", { chat: "c2" });
  assert.equal(d2.kind, "delta"); assert(d2.tokens * 2 < d2.full_tokens, `delta ${d2.tokens} vs full ${d2.full_tokens}`);
  assert(d2.text.includes("AssertionError") && d2.text.includes("already in your context"));
  await paste(M.llmReply(d2.text));
  b = await api("board");
  const c2 = b.chats.find((c) => c.id === "c2");
  assert.equal(c2.issue, "S3"); assert.equal(c2.kind, "delta"); // S3 reuses the chat that holds convert.py

  // S3: a question first, then done
  const d3 = await api("packet", { chat: "c2" });
  await paste(M.llmReply(d3.text));
  assert.equal((await chatOf("c2")).status, "needs_input");
  await assert.rejects(() => api("packet", { chat: "c2" }), /unanswered/);
  await api("accept", { chat: "c2" });
  const d4 = await api("packet", { chat: "c2" });
  assert(d4.text.includes("Should --align be on by default?"));
  await paste(M.llmReply(d4.text));
  s = await api("status");
  assert.equal(s.phase, "done"); assert(M.flags().finished && M.flags().delta);
  b = await api("board");
  assert(b.tokens.saved > 0 && b.events.some((e) => e.kind === "finished"));

  // routing errors
  M.reset();
  await api("approve", {});
  await relay("c1");
  assert.match((await api("paste", { text: "<<<CHATOP chat=c9 turn=1>>>\n<<<END>>>" })).errors[0], /unknown chat c9/);
  assert.match((await api("paste", { text: "hello" })).errors[0], /No <<<CHATOP/);
  console.log("mock scenario ok");
})().catch((e) => { console.error(e); process.exit(1); });
