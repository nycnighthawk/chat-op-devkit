/* Runs the whole lab-5 scenario against the mock backend with node: node mock/scenario.test.js */
"use strict";
require("./backend.js");
const assert = require("assert");
const M = globalThis.MOCK;
M.setApplyDelay(0);
const api = (p, b, pid) => M.api(p, b, pid);
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

  // ---- stages: who acts next, and the "I pasted it" flag
  M.reset();
  await api("approve", {});
  assert.equal((await chatOf("c1")).stage, "send");
  await api("packet", { chat: "c1" });
  assert.deepEqual([(await chatOf("c1")).stage, (await chatOf("c1")).owner], ["paste", "you"]);
  await assert.rejects(() => api("chat/sent", { chat: "c1", sent: true }).then(() => api("chat/sent", { chat: "c9" })), /unknown chat/);
  await api("chat/sent", { chat: "c1" });
  let c1 = await chatOf("c1");
  assert.equal(c1.stage, "waiting"); assert(c1.sent_at > 0 && c1.sent_at < Date.now());
  await api("chat/sent", { chat: "c1", sent: false });
  assert.equal((await chatOf("c1")).stage, "paste");
  await api("chat/sent", { chat: "c1" });
  await paste(M.llmReply((await api("packet", { chat: "c1" })).text));
  assert.equal((await chatOf("c1")).stage, "closed");
  await assert.rejects(() => api("chat/sent", { chat: "c1" }), /no packet out/);
  // a rejected reply sends the chat back to "fix" until the repair prompt is flagged as pasted
  const q2 = await relay("c3");
  await api("chat/sent", { chat: "c3" });
  const rej = await paste(q2.reply);
  assert.equal((await chatOf("c3")).stage, "fix");
  await api("chat/sent", { chat: "c3" });
  assert.equal((await chatOf("c3")).stage, "waiting");
  assert.equal((await api("board")).summary.waiting, 1);

  // ---- the hub: several projects, each keeps its own state
  const hub = M.listProjects();
  assert.deepEqual(hub.map((x) => x.id).sort(), ["csv2md", "docs-site", "notes-api"]);
  const byId = Object.fromEntries(hub.map((x) => [x.id, x]));
  assert.equal(byId["notes-api"].summary.your_move, 2);      // c3 packet to copy + c4 question
  assert.equal(byId["notes-api"].summary.waiting, 1);        // c2 flagged as pasted minutes ago
  assert(Date.now() / 1000 - byId["notes-api"].oldest_wait > 200);
  assert.equal(byId["docs-site"].phase, "done"); assert.equal(byId["docs-site"].summary.percent, 100);
  M.reset();
  assert.equal(M.listProjects().find((x) => x.id === "csv2md").summary.your_move, 1); // plan waits for approval
  const nb = (await api("board", {}, "notes-api")).chats;
  assert.deepEqual(nb.map((c) => c.stage), ["closed", "waiting", "send", "answer"]);
  // act in notes-api: answer c4, copy c3, the csv2md project is untouched
  await api("accept", { chat: "c4" }, "notes-api");
  const np = await api("packet", { chat: "c3" }, "notes-api");
  assert(np.text.includes("project `notes-api`"));
  assert.equal((await api("status")).phase, "plan");
  // the pending reply in c2 (flagged pasted) can be pasted in any order and closes N1; N3 becomes ready
  const c2pkt = (await api("packet", { chat: "c2" }, "notes-api")).text;
  await api("paste", { text: M.llmReply(c2pkt) }, "notes-api"); await settle();
  const nb2 = await api("board", {}, "notes-api");
  assert.equal(nb2.issues.find((i) => i.id === "N1").status, "done");
  assert(nb2.summary.issues_done === 2);
  console.log("mock scenario ok");
})().catch((e) => { console.error(e); process.exit(1); });
