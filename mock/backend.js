/* In-browser stand-in for the chatop server, used by the standalone mock UI (docs/chatop-mock-ui.html).
 *
 * It speaks the same JSON API as src/chatop/ui/web.py (status, board, packet, paste, dispatch, ...) so the REAL web
 * page runs unchanged against it through window.CHATOP_API. The scheduler/routing/delta rules mirror
 * src/chatop/app/lanes.py; builds, tests and the LLM are scripted: this proves the workflow, not the code.
 * No DOM access in this file, so it is unit-tested with node (mock/scenario.test.js).
 */
(function (root) {
  "use strict";
  // Three projects share one engine: csv2md is the live walkthrough, the other two start mid-flight so the hub has
  // something to show (a packet waiting to be copied, one flagged as pasted, a question, a finished project).
  const CSV_ISSUES = [
    { id: "S0", title: "Walking skeleton", touches: ["pyproject.toml", "src/csv2md/__init__.py"], depends: [] },
    { id: "S1", title: "Converter core", touches: ["src/csv2md/convert.py"], depends: ["S0"] },
    { id: "S2", title: "Numeric columns", touches: ["src/csv2md/align.py"], depends: ["S0"] },
    { id: "S3", title: "CLI with --align", touches: ["src/csv2md/cli.py", "src/csv2md/convert.py", "src/csv2md/align.py"], depends: ["S1", "S2"] },
  ];
  // what the scripted "LLM" does on its 1st, 2nd, ... reply for an issue
  const CSV_SCRIPT = { S0: ["pass"], S1: ["fail", "pass"], S2: ["syntax", "pass"], S3: ["ask", "pass"] };
  const SPEC = ("## SPEC: csv2md\n\n### Architecture\n- `csv2md.convert` pure core: `to_markdown(rows) -> str`\n- `csv2md.align` pure helper: `numeric_columns(rows) -> set[int]`\n" +
    "- `csv2md.cli` thin I/O shell. Import rule: cli -> convert, align; core imports only the stdlib.\n\n### Data model\nRows are `list[list[str]]`; the first row is the header.\n\n" +
    "### Errors\nA missing file prints to stderr and returns 2.\n\n### Test strategy\nUnit tests for the core (AC-1.x, AC-3.1); CLI tests with injected stdin and a temp file (AC-2.x, AC-3.2).\n").repeat(3);
  const PRD = "## PRD: csv2md\nGoal: turn CSV files into Markdown tables for READMEs.\nAC-1.1 basic table. AC-1.2 pipes escaped. AC-1.3 ragged rows padded.\nAC-2.1 stdin. AC-2.2 file. AC-3.1 numeric columns detected. AC-3.2 --align right-aligns them.\n".repeat(3);
  const RULES = "You are the engineer-of-record for this project, working through chatop, a copy/paste harness. You cannot run anything yourself.\n" +
    "Operating rules: this packet is your whole world; reply with exactly ONE CHATOP block in a 4-backtick chatop fence; batch everything in one reply; never invent command output; Python must be fully type-annotated.\n";
  const CONTRACT = "Your reply MUST contain exactly this envelope (copy the first line verbatim):\n@@summary <one line> / @@test <path> / @@file <path> / @@edit <path> / @@ask / @@need / @@decision / @@advance ... <<<END>>>\n".repeat(2);
  const CSV_REPO = "src/csv2md/\n  __init__.py\n  convert.py\n  align.py\n  cli.py\ntests/\n";
  const NOTES_ISSUES = [
    { id: "N0", title: "Project skeleton", touches: ["pyproject.toml", "src/notes/__init__.py"], depends: [] },
    { id: "N1", title: "Note model + store", touches: ["src/notes/store.py"], depends: ["N0"] },
    { id: "N2", title: "HTTP routes", touches: ["src/notes/api.py"], depends: ["N0"] },
    { id: "N5", title: "Rate limiting", touches: ["src/notes/limits.py"], depends: ["N0"] },
    { id: "N3", title: "Search endpoint", touches: ["src/notes/search.py"], depends: ["N1"] },
    { id: "N4", title: "API docs", touches: ["docs/api.md"], depends: ["N2", "N3"] },
  ];
  const DOCS_ISSUES = [
    { id: "D0", title: "Site skeleton", touches: ["mkdocs.yml"], depends: [] },
    { id: "D1", title: "Getting started page", touches: ["docs/start.md"], depends: ["D0"] },
    { id: "D2", title: "Reference pages", touches: ["docs/ref.md"], depends: ["D0"] },
  ];
  const SCENARIOS = {
    csv2md: { name: "csv2md", track: "new", blurb: "CSV to Markdown tables CLI", issues: CSV_ISSUES, script: CSV_SCRIPT, repo: CSV_REPO, plan: true },
    "notes-api": { name: "notes-api", track: "continue", blurb: "Add rate limiting and search to the notes API", issues: NOTES_ISSUES, repo: "src/notes/\n  __init__.py\n  store.py\n  api.py\ntests/\n", script: { N2: ["fail", "pass"] } },
    "docs-site": { name: "docs-site", track: "adopt", blurb: "Documentation site for the toolkit", issues: DOCS_ISSUES, repo: "docs/\nmkdocs.yml\n", script: {} },
  };

  const tok = (t) => Math.ceil(t.length / 4);
  const overlaps = (a, b) => a.some((x) => b.includes(x));
  const timing = { apply: 1400 };
  const projects = {}; // id -> state; every function below works on `st`, the project selected by within()
  let st = null;
  function within(pid, fn) {
    const proj = projects[pid];
    if (!proj) throw Object.assign(new Error("unknown project " + pid), { mock: true });
    const prev = st; st = proj;
    try { return fn(); } finally { st = prev; }
  }

  // who acts next (mirrors src/chatop/domain/stage.py)
  const STAGE_OWNER = { send: "you", paste: "you", fix: "you", answer: "you", blocked: "you", waiting: "llm", applying: "chatop", closed: "nobody" };
  function stageOf(c) {
    if (c.status === "queued" || c.status === "ready") return "send";
    if (c.status === "awaiting_reply") return c.sentAt ? "waiting" : c.repair ? "fix" : "paste";
    return { applying: "applying", needs_input: "answer", blocked: "blocked", done: "closed" }[c.status];
  }

  function fresh(id) {
    const sc = SCENARIOS[id];
    const proj = {
      id, sc, phase: sc.plan ? "plan" : "slice", status: sc.plan ? "awaiting_approval" : "ready", maxPar: 3, seq: 0, events: [], jobs: [], chats: [], flags: {},
      replies: {}, lock: Promise.resolve(), issues: sc.issues.map((i) => Object.assign({}, i, { status: "todo", lane: null, attempts: 0 })),
    };
    projects[id] = proj;
    if (id === "notes-api") within(id, seedNotes);
    if (id === "docs-site") within(id, seedDocs);
  }
  function resetAll() { Object.keys(SCENARIOS).forEach(fresh); }

  const ts = () => new Date().toTimeString().slice(0, 8);
  function event(kind, chat, issue, text) {
    st.seq += 1;
    st.events.push({ seq: st.seq, ts: ts(), kind, chat, issue, text });
    st.events = st.events.slice(-200);
  }
  const issue = (id) => st.issues.find((i) => i.id === id);
  const chat = (id) => st.chats.find((c) => c.id === id);
  const fail = (msg) => { const e = new Error(msg); e.mock = true; throw e; };

  function newChat() {
    const c = { id: "c" + (st.chats.length + 1), title: "", issue: null, status: "queued", turn: 0, seen: [], tokensSent: 0, tokensFull: 0,
      issuesDone: [], lastSummary: "", lastResult: [], evidence: "", questions: [], repair: "", forceFull: false, kind: "", packet: "", packetFull: 0 };
    st.chats.push(c);
    return c;
  }
  function assign(is, c) {
    const reused = !!c;
    if (!c) c = newChat(); else c.status = "ready";
    c.issue = is.id; c.title = is.id + " · " + is.title; c.evidence = ""; c.questions = []; c.repair = "";
    is.status = "active"; is.lane = c.id;
    event("ready", c.id, is.id, is.id + (reused ? " continues in the same chat (delta packet)" : " opens a new chat (full packet)"));
    return { chat: c.id, issue: is.id, reused };
  }
  function chooseChat(is) {
    let best = null, score = 0;
    for (const c of st.chats) {
      if (c.status !== "done" || c.issuesDone.length >= 3) continue;
      const s = is.touches.filter((t) => c.seen.includes("file:" + t)).length;
      if (s > score) { best = c; score = s; }
    }
    return best;
  }
  function dispatch() {
    if (st.phase !== "slice") fail("dispatch is for the slice phase (current phase: " + st.phase + ")");
    const out = [];
    const active = st.issues.filter((i) => i.status === "active");
    let capacity = Math.max(0, st.maxPar - active.length);
    const running = active.slice();
    for (const is of st.issues) {
      if (capacity <= 0) break;
      if (is.status !== "todo" || !is.depends.every((d) => issue(d).status === "done")) continue;
      if (running.some((r) => overlaps(is.touches, r.touches))) continue;
      out.push(assign(is, chooseChat(is)));
      running.push(is); capacity -= 1;
    }
    return out;
  }
  const sendable = (c) => c.status === "queued" || c.status === "ready";
  function nextUp() {
    const r = st.chats.filter(sendable).sort((a, b) => (a.status === "ready" ? 0 : 1) - (b.status === "ready" ? 0 : 1) || a.id.localeCompare(b.id));
    return r.length ? r[0] : null;
  }

  // ---- seeds for the two projects that start mid-flight
  function remember(c, is) {
    ["doc:docs/SPEC.md", "doc:docs/PRD.md", "repomap"].concat(is.touches.map((t) => "file:" + t)).forEach((k) => { if (!c.seen.includes(k)) c.seen.push(k); });
  }
  function seedNotes() {
    const n0 = issue("N0"), c1 = newChat();
    n0.status = "done"; c1.issuesDone = ["N0"]; c1.status = "done"; c1.turn = 1; c1.title = "N0 · " + n0.title; c1.tokensSent = c1.tokensFull = 2300; remember(c1, n0);
    const c2 = newChat(), n1 = issue("N1");               // pasted 4 minutes ago: waiting for the LLM
    n1.status = "active"; n1.lane = c2.id; c2.issue = "N1"; c2.title = "N1 · " + n1.title; c2.turn = 1; c2.status = "awaiting_reply";
    c2.sentAt = Date.now() - 4 * 60000; c2.kind = "full"; c2.packet = packetText(c2, "full"); c2.packetFull = c2.tokensSent = c2.tokensFull = tok(c2.packet); remember(c2, n1);
    const c3 = newChat(), n2 = issue("N2");               // chatop has the packet; you have to copy it
    n2.status = "active"; n2.lane = c3.id; c3.issue = "N2"; c3.title = "N2 · " + n2.title; c3.status = "queued";
    const c4 = newChat(), n5 = issue("N5");               // the LLM asked a question
    n5.status = "active"; n5.lane = c4.id; c4.issue = "N5"; c4.title = "N5 · " + n5.title; c4.turn = 1; c4.status = "needs_input"; remember(c4, n5);
    c4.kind = "full"; c4.packet = packetText(c4, "full"); c4.packetFull = c4.tokensSent = c4.tokensFull = tok(c4.packet); st.replies.N5 = 1;
    c4.questions = [{ id: "q1", text: "Limit per API key or per IP address?", options: ["Per API key", "Per IP address"], recommended: ["Per API key"], multi: false, answer: null, other: "" }];
    st.seq = 4;
    st.events = [{ seq: 1, ts: "09:12:04", kind: "done", chat: "c1", issue: "N0", text: "N0 done (3f9a1c2)" }, { seq: 2, ts: "09:14:31", kind: "ready", chat: "c2", issue: "N1", text: "N1 opens a new chat (full packet)" },
      { seq: 3, ts: "09:14:31", kind: "ready", chat: "c3", issue: "N2", text: "N2 opens a new chat (full packet)" }, { seq: 4, ts: "09:18:50", kind: "question", chat: "c4", issue: "N5", text: "chat c4 has 1 question(s)" }];
  }
  function seedDocs() {
    const c = newChat();
    st.issues.forEach((i) => { i.status = "done"; remember(c, i); });
    c.issuesDone = st.issues.map((i) => i.id); c.status = "done"; c.turn = 4; c.title = "D2 · Reference pages"; c.tokensSent = 5200; c.tokensFull = 9100;
    st.phase = "done"; st.status = "done"; st.flags.finished = true; st.seq = 1;
    st.events = [{ seq: 1, ts: "Yesterday", kind: "finished", chat: null, issue: null, text: "all issues are done" }];
  }

  // ---- packets
  function packetText(c, kind) {
    const is = issue(c.issue);
    const head = "# CHATOP PACKET · project `" + st.sc.name + "` · chat " + c.id + " · turn " + c.turn + " · " + kind + " · issue " + is.id;
    const hdr = "<<<CHATOP chat=" + c.id + " turn=" + c.turn + ">>>";
    const task = "## Your task: " + is.id + "\n\n### Phase SLICE: " + is.id + " · " + is.title + " (attempt " + (is.attempts + 1) + ")\nTouches: " + is.touches.join(", ") + "\nDeliver the whole slice in ONE reply: the COMPLETE test suite first, then the implementation.\n";
    const ev = c.evidence ? "\n## Evidence (from chatop's last run)\n\n" + c.evidence + "\n" : "";
    const ans = c.answers ? "\n## Human input\n\n" + c.answers + "\n" : "";
    const files = is.touches.map((t) => "### Code: " + t + "\n`" + t + "`\n```\n(current content)\n```\n").join("\n");
    const state = "\n## State\n\n| id | status | chat |\n|---|---|---|\n" + st.issues.filter((i) => i.status !== "done").map((i) => "| " + i.id + " | " + i.status + " | " + (i.lane || "") + " |").join("\n") + "\n";
    if (kind === "full") {
      return head + "\n\n## Role and rules\n\n" + RULES + "\n## Reply contract\n\n```chatop\n" + hdr + "\n```\n" + CONTRACT + task + state + ans + ev +
        "\n## Doc: docs/SPEC.md\n\n" + SPEC + "\n## Doc: docs/PRD.md\n\n" + PRD + "\n## Code context for " + is.id + "\n\n" + files + "\n## Repo map\n\n" + st.sc.repo;
    }
    const known = ["doc:docs/SPEC.md", "doc:docs/PRD.md", "repomap"].concat(c.seen.filter((k) => k.startsWith("file:")));
    return head + "\n\n## Continuation\n\nYou are continuing this chat. Rules and reply format are unchanged. Start your reply with `" + hdr + "`.\n\n" + task + state + ans + ev +
      "\n## Already in your context\n\nSent earlier in this chat and unchanged, so not repeated: " + known.map((k) => "`" + k + "`").join(", ") + ". These are already in your context.\n";
  }
  function packet(body) {
    let c = body.chat ? chat(body.chat) : null;
    if (body.chat && !c) fail("unknown chat " + body.chat);
    if (!body.chat) { st.flags.nextUsed = true; if (st.phase === "slice") dispatch(); c = nextUp() || st.chats.find((x) => x.status === "awaiting_reply"); if (!c) fail("nothing to send: every chat is waiting for its reply, or no issue is ready"); }
    if (c.status === "needs_input") fail("chat " + c.id + " has unanswered questions (answer them first)");
    if (c.status === "blocked") fail("chat " + c.id + " is blocked; decide, then reset it");
    if (c.status === "applying") fail("chat " + c.id + " is being applied right now");
    if (c.status === "done" || !c.issue) fail("chat " + c.id + " is free: no issue assigned (run dispatch)");
    const fresh = sendable(c);
    if (c.status === "awaiting_reply" && !body.full && c.packet) {
      return { turn: c.turn, text: c.packet, tokens: tok(c.packet), notes: [], copied: false, chat: c.id, kind: c.kind, full_tokens: c.packetFull };
    }
    const kind = c.status === "queued" || c.forceFull || body.full ? "full" : "delta";
    if (fresh) { c.turn += 1; c.status = "awaiting_reply"; c.sentAt = null; }
    const text = packetText(c, kind);
    const fullText = kind === "full" ? text : packetText(c, "full");
    c.packet = text; c.kind = kind; c.packetFull = tok(fullText); c.forceFull = false;
    if (fresh) { c.tokensSent += tok(text); c.tokensFull += tok(fullText); }
    const is = issue(c.issue);
    ["doc:docs/SPEC.md", "doc:docs/PRD.md", "repomap"].concat(is.touches.map((t) => "file:" + t)).forEach((k) => { if (!c.seen.includes(k)) c.seen.push(k); });
    c.answers = "";
    if (kind === "delta") st.flags.delta = true;
    const awaiting = st.chats.filter((x) => x.status === "awaiting_reply").length;
    if (awaiting >= 2) st.flags.twoChats = true;
    return { turn: c.turn, text, tokens: tok(text), notes: kind === "delta" ? ["delta: unchanged context not resent"] : [], copied: false, chat: c.id, kind, full_tokens: tok(fullText) };
  }

  // ---- replies
  function header(text) {
    const m = /^<<<CHATOP((?:\s+[a-z]+=[\w-]+)*)\s*>>>\s*$/m.exec(text);
    if (!m) return null;
    const a = {}; (m[1].match(/([a-z]+)=([\w-]+)/g) || []).forEach((p) => { const [k, v] = p.split("="); a[k] = v; });
    return { chat: a.chat || null, turn: a.turn ? parseInt(a.turn, 10) : null };
  }
  function route(text) {
    if (/^\s*# CHATOP PACKET/m.test(text.slice(0, 300))) return { ok: false, chat: null, error: "This is a chatop PACKET, not a reply. Paste it into the chat, then paste back the answer." };
    const h = header(text);
    if (!h) return { ok: false, chat: null, error: "No <<<CHATOP chat=cN turn=N>>> block found in what you pasted." };
    if (h.chat) return chat(h.chat) ? { ok: true, chat: h.chat } : { ok: false, chat: null, error: "unknown chat " + h.chat + " (known chats: " + (st.chats.map((c) => c.id).join(", ") || "none") + ")" };
    const w = st.chats.filter((c) => c.status === "awaiting_reply");
    if (w.length === 1) return { ok: true, chat: w[0].id };
    if (!w.length) return { ok: false, chat: null, error: "No chat is waiting for a reply. Copy a packet first." };
    const same = w.filter((c) => h.turn !== null && c.turn === h.turn);
    if (same.length === 1) return { ok: true, chat: same[0].id };
    return { ok: false, chat: null, error: "The reply has no chat=… in its header and several chats are waiting (" + w.map((c) => c.id).join(", ") + ")." };
  }
  function unrouted(error) {
    const w = st.chats.find((c) => c.status === "awaiting_reply");
    const ex = w ? "<<<CHATOP chat=" + w.id + " turn=" + w.turn + ">>>" : "<<<CHATOP chat=c1 turn=1>>>";
    return { ok: false, errors: [error], changes: [], checks: [], red_ok: null, slice_done: false, messages: [], next_packet: null, status: "", chat: null,
      repair_prompt: "chatop could not route your reply: " + error + "\n\nResend the COMPLETE reply starting with the header copied from the packet, for example `" + ex + "`." };
  }
  function result(c, over) {
    return Object.assign({ ok: true, errors: [], changes: [], checks: [], red_ok: null, slice_done: false, messages: [], repair_prompt: null, next_packet: null, status: c.status, chat: c.id }, over);
  }
  function reject(c, errors) {
    const repair = "chatop could not apply your reply for chat " + c.id + ", turn " + c.turn + ". Nothing was changed.\n\nProblems:\n" + errors.map((e) => "- " + e).join("\n") +
      "\n\nResend the COMPLETE corrected reply starting with `<<<CHATOP chat=" + c.id + " turn=" + c.turn + ">>>`.";
    c.repair = repair; c.sentAt = null;
    event("rejected", c.id, c.issue, "reply for " + c.id + " was rejected (" + errors.length + " problem(s)); repair prompt ready");
    return result(c, { ok: false, errors, repair_prompt: repair, messages: ["repair prompt ready"] });
  }
  function applyReply(c, text) {
    const h = header(text);
    const outcome = (/^@@mock outcome=(\w+)/m.exec(text) || [null, "pass"])[1];
    const is = issue(c.issue);
    if (c.status !== "awaiting_reply") return reject(c, ["chat " + c.id + " is not waiting for a reply (status: " + c.status + "); build its packet first"]);
    if (h.turn !== null && h.turn !== c.turn) return reject(c, ["reply is for turn " + h.turn + " but chat " + c.id + " is on turn " + c.turn + " (stale paste?)"]);
    const oldest = st.chats.filter((x) => x.status === "awaiting_reply").sort((a, b) => a.id.localeCompare(b.id))[0];
    if (oldest && oldest.id !== c.id) st.flags.outOfOrder = true;
    if (outcome === "syntax") {
      st.flags.batchReject = true;
      return reject(c, ["syntax error in src/csv2md/align.py:1:20: SyntaxError: '(' was never closed", "syntax error in tests/test_align.py:3:18: SyntaxError: '(' was never closed"]);
    }
    c.status = "applying";
    c.repair = ""; c.sentAt = null;
    const files = (text.match(/^@@(?:test|file|edit) (\S+)/gm) || []).map((l) => l.split(" ")[1]);
    const changes = files.map((f) => "A " + f + (f.includes("test") ? " [test]" : " [code]"));
    const summary = (/^@@summary (.*)$/m.exec(text) || [null, ""])[1];
    c.lastSummary = summary;
    c.lastResult = changes.slice();
    if (outcome === "fail") {
      is.attempts += 1;
      const other = st.chats.some((x) => x.id !== c.id);
      if (other) st.flags.failingLaneHeld = true;
      c.evidence = "### test: FAIL (exit code 1, 0.3s) `python -m pytest -q`\n```\nE   AssertionError: assert 'x | y' in '| h |\\n| --- |\\n| x | y |\\n'\ntests/test_convert.py:9: AssertionError\n1 failed, 3 passed\n```\n### typecheck: PASS";
      c.lastResult.push("test: FAIL", "typecheck: PASS");
      c.status = "ready";
      event("ready", c.id, is.id, "chat " + c.id + " replied: next packet ready");
      return result(c, { changes, red_ok: true, checks: [{ name: "test", code: 1, seconds: 0.3 }, { name: "typecheck", code: 0, seconds: 0.1 }], messages: ["failing code is held back from the tree; other chats are unaffected"] });
    }
    if (outcome === "ask") {
      c.questions = [{ id: "q1", text: "Should --align be on by default?", options: ["No, opt-in flag", "Yes, always"], recommended: ["No, opt-in flag"], multi: false, answer: null, other: "" }];
      c.status = "needs_input";
      event("question", c.id, is.id, "chat " + c.id + " has 1 question(s)");
      return result(c, { changes: [] });
    }
    // pass: commit, free the chat, unblock dependents
    const failingElsewhere = st.chats.some((x) => x.id !== c.id && x.status === "ready" && x.evidence);
    if (failingElsewhere) st.flags.isolated = true;
    is.status = "done"; is.lane = null; c.issuesDone.push(is.id); c.issue = null; c.status = "done"; c.evidence = ""; c.questions = [];
    c.lastResult.push("test: PASS", "typecheck: PASS");
    const sha = Math.random().toString(16).slice(2, 9);
    event("done", c.id, is.id, is.id + " done (" + sha + ")");
    if (st.issues.every((i) => i.status === "done")) { st.phase = "done"; st.status = "done"; event("finished", null, null, "all issues are done"); st.flags.finished = true; }
    else dispatch();
    return result(c, { changes, slice_done: true, red_ok: true, checks: [{ name: "test", code: 0, seconds: 0.3 }, { name: "typecheck", code: 0, seconds: 0.1 }], messages: ["issue " + is.id + " complete in " + c.id + ", committed " + sha] });
  }
  function paste(body) {
    if (st.phase !== "slice") fail("nothing is waiting for a reply yet: approve the plan first");
    const r = route(body.text);
    if (!r.ok) return Object.assign({ job: null }, unrouted(r.error));
    const job = { id: "j" + (st.jobs.length + 1), chat: r.chat, status: "running", result: null, error: "" };
    st.jobs.push(job);
    const proj = st, pid = st.id;
    proj.lock = proj.lock.then(() => new Promise((resolve) => {
      const c = within(pid, () => chat(r.chat));
      if (c.status === "awaiting_reply") { c.status = "applying"; }
      setTimeout(() => {
        within(pid, () => {
          try {
            if (c.status === "applying") c.status = "awaiting_reply";
            job.result = applyReply(c, body.text); job.status = "done";
          } catch (e) { job.status = "error"; job.error = String(e.message || e); }
        });
        resolve();
      }, timing.apply);
    }));
    return { ok: true, chat: r.chat, job: job.id };
  }

  // ---- views
  function chatView(c) {
    const is = c.issue ? issue(c.issue) : null;
    const stage = stageOf(c);
    return { id: c.id, title: c.title, issue: c.issue, status: c.status, turn: c.turn, stage, owner: STAGE_OWNER[stage], sent_at: c.sentAt ? c.sentAt / 1000 : null, issue_status: is ? is.status : null, attempts: is ? is.attempts : 0,
      can_send: sendable(c), kind: c.status === "queued" || c.forceFull ? "full" : "delta", tokens_sent: c.tokensSent, tokens_full: c.tokensFull,
      issues_done: c.issuesDone.slice(), last_summary: c.lastSummary, last_result: c.lastResult.slice(), repair: c.repair, evidence: c.evidence,
      questions: c.questions.filter((q) => q.answer === null && !q.other) };
  }
  function hint(nxt) {
    const waiting = st.chats.filter((c) => c.status === "awaiting_reply").map((c) => c.id);
    if (nxt) return "copy the packet for chat " + nxt.id + ", paste it in that chat" + (waiting.length ? "; replies from " + waiting.join(", ") + " can be pasted any time" : "");
    if (waiting.length) return "waiting for " + waiting.join(", ") + ": paste each reply as it arrives, chatop routes it by header";
    if (st.chats.some((c) => c.status === "needs_input")) return "chats are waiting for your answers";
    return st.phase === "slice" ? "nothing to send: every chat is waiting for its reply, or no issue is ready" : "done";
  }
  function summarize() {
    const stages = st.chats.map(stageOf), done = st.issues.filter((i) => i.status === "done").length, total = st.issues.length;
    return { your_move: stages.filter((x) => STAGE_OWNER[x] === "you").length, waiting: stages.filter((x) => x === "waiting").length, applying: stages.filter((x) => x === "applying").length,
      closed: stages.filter((x) => x === "closed").length, issues_done: done, issues_total: total, percent: total ? Math.round(100 * done / total) : 0 };
  }
  function board() {
    const nxt = nextUp();
    const sent = st.chats.reduce((a, c) => a + c.tokensSent, 0), full = st.chats.reduce((a, c) => a + c.tokensFull, 0);
    return {
      mode: "parallel", phase: st.phase, status: st.status, max_parallel: st.maxPar, chats: st.chats.map(chatView),
      issues: st.issues.map((i) => ({ id: i.id, title: i.title, status: i.status, depends: i.depends, touches: i.touches, chat: i.lane, attempts: i.attempts,
        waiting_on: i.depends.filter((d) => issue(d).status !== "done") })),
      next_up: nxt ? { chat: nxt.id, issue: nxt.issue, kind: nxt.status === "queued" || nxt.forceFull ? "full" : "delta" } : null,
      summary: summarize(), tokens: { sent, full, saved: Math.max(0, full - sent) }, event_seq: st.seq, events: st.events.slice(-40), hint: hint(nxt), jobs: st.jobs.slice(-20),
    };
  }
  function status() {
    const b = board();
    const planHint = "Review the plan: " + st.issues.length + " issues, S1 and S2 can run in parallel chats. Approve to turn it into issues and open chats.";
    return {
      mode: "parallel", chats: st.phase === "plan" ? [] : b.chats, event_seq: st.seq, max_parallel: st.maxPar, project: st.sc.name, track: st.sc.track, phase: st.phase, status: st.status,
      turn: 5, hint: st.phase === "plan" ? planHint : b.hint, slice: null, slices: st.issues.map((i) => ({ id: i.id, title: i.title, status: i.status })),
      questions: [], proposed_checks: {}, checks: { test: "python -m pytest -q", typecheck: "python -m mypy --strict src" }, decisions: ["pure core, thin CLI"],
      history: ["T5 plan: 4 issues, S1 and S2 are independent"], evidence: "", clipboard: "mock",
    };
  }
  function answers(chatId, qid, choices, other) {
    const owners = st.chats.filter((c) => (!chatId || c.id === chatId) && c.questions.some((q) => q.id === qid));
    if (owners.length !== 1) fail("no pending question " + qid);
    const c = owners[0], q = c.questions.find((x) => x.id === qid);
    q.answer = choices; q.other = other || "";
    if (c.questions.every((x) => x.answer !== null || x.other)) {
      c.answers = c.questions.map((x) => "- **" + x.id + "** " + x.text + " → " + (x.answer || []).join(", ")).join("\n");
      c.status = "ready"; st.flags.answered = true;
      event("ready", c.id, c.issue, "chat " + c.id + ": answers recorded, next packet ready");
    }
  }

  async function api(path, body, pid) { return within(pid || "csv2md", () => apiSync(path, body)); }
  function apiSync(path, body) {
    body = body || {};
    switch (path) {
      case "status": return status();
      case "board": return board();
      case "approve":
        if (st.status !== "awaiting_approval") fail("nothing to approve (status: " + st.status + ")");
        st.phase = "slice"; st.status = "ready"; st.flags.approved = true; dispatch(); return status();
      case "reject": fail("the mock plan cannot be sent back");
      case "next": fail(st.phase === "plan" ? "plan is waiting for approval (approve it first)" : "use the chat cards: each chat has its own packet");
      case "dispatch": return dispatch();
      case "packet": return packet(body);
      case "paste": return paste(body);
      case "apply": fail("this is the parallel board: paste replies into the box on top");
      case "job": return st.jobs.find((j) => j.id === body.id) || fail("no such job");
      case "chat/reset": { const c = chat(body.chat); if (!c) fail("unknown chat " + body.chat); c.seen = []; c.forceFull = true; c.repair = ""; c.sentAt = null;
        if (c.status === "blocked") c.status = "ready"; event("ready", c.id, c.issue, "chat " + c.id + " reset: next packet is a full one"); return board(); }
      case "chat/sent": { const c = chat(body.chat); if (!c) fail("unknown chat " + body.chat);
        if (c.status !== "awaiting_reply") fail("chat " + c.id + " has no packet out (status: " + c.status + "); copy its packet first");
        c.sentAt = body.sent === false ? null : Date.now(); if (c.sentAt) st.flags.flaggedSent = true; return board(); }
      case "accept": { const targets = st.chats.filter((c) => c.status === "needs_input" && (!body.chat || c.id === body.chat));
        targets.forEach((c) => c.questions.forEach((q) => { if (q.answer === null) answers(c.id, q.id, q.recommended.slice(), ""); })); return status(); }
      case "answer": answers(body.chat, body.qid, body.choices, body.other); return status();
      case "configure": if (body.key !== "max_parallel") fail("unknown or non-scalar option: " + body.key); st.maxPar = Math.max(1, parseInt(body.value, 10) || 1); return { max_parallel: st.maxPar };
      case "watch": return { last_seen: null, result: null };
      case "undo": fail("undo is not available once parallel chats are in use; use git revert");
      case "checks/accept": return {};
      case "init": case "feature": fail("the mock is a fixed scenario; use Restart");
      default: fail("unknown endpoint " + path);
    }
  }

  // ---- the scripted LLM (used by the simulated chat tabs)
  const CODE = {
    S0: "@@test tests/test_smoke.py\nimport csv2md\n\n\ndef test_version() -> None:\n    assert csv2md.__version__ == \"0.1.0\"\n@@end\n@@file pyproject.toml\n[project]\nname = \"csv2md\"\nversion = \"0.1.0\"\n@@end\n@@file src/csv2md/__init__.py\n__version__ = \"0.1.0\"\n@@end",
    S1: "@@test tests/test_convert.py\nfrom csv2md.convert import to_markdown\n\n\ndef test_pipe_escaped() -> None:  # AC-1.2\n    assert \"x \\\\| y\" in to_markdown([[\"h\"], [\"x | y\"]])\n...\n@@end\n@@file src/csv2md/convert.py\ndef to_markdown(rows: list[list[str]]) -> str:\n    ...\n@@end",
    S2: "@@test tests/test_align.py\nfrom csv2md.align import numeric_columns\n\n\ndef test_detects_numeric_columns() -> None:  # AC-3.1\n    assert numeric_columns([[\"n\", \"t\"], [\"1\", \"a\"]]) == {0}\n...\n@@end\n@@file src/csv2md/align.py\ndef numeric_columns(rows: list[list[str]]) -> set[int]:\n    ...\n@@end",
    S3: "@@test tests/test_cli.py\nfrom csv2md.cli import main\n\n\ndef test_align_flag_right_aligns_numbers() -> None:  # AC-3.2\n    ...\n@@end\n@@edit src/csv2md/convert.py\n<<<<<<< SEARCH\n...\n=======\n...\n>>>>>>> REPLACE\n@@end\n@@file src/csv2md/cli.py\n...\n@@end",
  };
  function generic(id) {
    const is = issue(id), t = "tests/test_" + id.toLowerCase() + ".py";
    return "@@test " + t + "\nfrom pkg import thing\n\n\ndef test_" + id.toLowerCase() + "() -> None:  # " + is.title + "\n    assert thing() is True\n@@end\n" +
      is.touches.map((x) => "@@file " + x + "\n...\n@@end").join("\n");
  }
  function llmReply(packetText) {
    const m = /project `([\w-]+)` · chat (\w+) · turn (\d+) · (full|delta) · issue (\w+)/.exec(packetText);
    if (!m) return null;
    const [, project, chatId, turn, , issueId] = m;
    return within(project, () => scripted(chatId, turn, issueId));
  }
  function scripted(chatId, turn, issueId) {
    const n = st.replies[issueId] || 0;
    st.replies[issueId] = n + 1;
    const script = st.sc.script[issueId] || ["pass"];
    const outcome = script[Math.min(n, script.length - 1)];
    const summary = { pass: issueId + " done: all tests written first, implementation passes", fail: issueId + " first try (one test will fail)", syntax: issueId + " (contains two typos chatop will catch)", ask: issueId + ": one question before I implement" }[outcome];
    let body = CODE[issueId] || generic(issueId);
    if (outcome === "syntax") body = "@@test tests/test_align.py\nclass TestNumeric(\n    def test_detects(self) -> None: ...\n@@end\n@@file src/csv2md/align.py\ndef numeric_columns(rows:\n    return set()\n@@end";
    if (outcome === "ask") body = "@@ask q1 single\nShould --align be on by default?\n- [x] No, opt-in flag\n- [ ] Yes, always\n@@end";
    return "Here is the reply:\n````chatop\n<<<CHATOP chat=" + chatId + " turn=" + turn + ">>>\n@@summary " + summary + "\n" + body + "\n@@mock outcome=" + outcome + "   (scripted)\n<<<END>>>\n````\n";
  }

  // ---- hub: one line per project, what needs the human first
  function listProjects() {
    return Object.keys(projects).map((id) => within(id, () => {
      const sm = summarize(), plan = st.status === "awaiting_approval";
      const yourMove = sm.your_move + (plan ? 1 : 0);
      const sent = st.chats.filter((c) => stageOf(c) === "waiting").map((c) => c.sentAt);
      const next = plan ? "Approve the plan" : st.phase === "done" ? "Finished" :
        (() => { const c = st.chats.map((x) => [x, stageOf(x)]).filter(([, g]) => STAGE_OWNER[g] === "you").sort((a, b) => ["paste", "fix", "answer", "blocked", "send"].indexOf(a[1]) - ["paste", "fix", "answer", "blocked", "send"].indexOf(b[1]))[0];
          return c ? { send: "Copy the packet for ", paste: "Confirm you pasted ", fix: "Send the repair prompt to ", answer: "Answer the question from ", blocked: "Decide for " }[c[1]] + c[0].id : sm.waiting ? "Waiting for the LLM" : "Nothing to do"; })();
      return { id, name: st.sc.name, track: st.sc.track, blurb: st.sc.blurb, phase: st.phase, summary: Object.assign({}, sm, { your_move: yourMove }), next,
        oldest_wait: sent.length ? Math.min.apply(null, sent) / 1000 : null,
        chats: st.chats.map((c) => ({ id: c.id, stage: stageOf(c), title: c.title })), events: st.seq };
    }));
  }

  resetAll();
  root.MOCK = {
    api, llmReply, reset: resetAll, listProjects,
    flags: (pid) => projects[pid || "csv2md"].flags, state: (pid) => projects[pid || "csv2md"], board: (pid) => within(pid || "csv2md", board),
    setApplyDelay: (ms) => { timing.apply = ms; },
    idle: () => Promise.all(Object.values(projects).map((p) => p.lock)),
  };
})(typeof window !== "undefined" ? window : globalThis);
