# Labs

Each lab has a `steps.txt` (what you type) and `replies/` (reference LLM answers). Run a lab in one of two ways:

* **Offline replay** (verifies your toolchain; no LLM needed): `python labs/run_lab.py <lab> --workdir /tmp/x`
* **For real**: follow `python labs/run_lab.py <lab> --show`. At each `reply` step, paste the packet into your chat
  and apply the LLM's actual answer. Compare it with the reference reply to calibrate your model.

Run the labs from an activated venv that has pytest and mypy (the check commands call `python -m …`).

## Lab 0: setup (10 min)
1. Install (see GETTING-STARTED). `chatop doctor` should be all ok, except checks.
2. `pytest -q` in chat-op-devkit. You should see all tests pass (about 130), including the 5 lab replays and the mock UI scenario.
3. **Exercise:** `CHATOP_CLIPBOARD=file chatop doctor`. Note how the clipboard backend changes.

## Lab 1: new project, from a vague idea to shipped slices (`labs/new-project`)
**Goal:** experience the full `new` track: IDEA → REFINE → PRD → SPEC → PLAN → 3 slices.
**Observe:**
* Turn 1: questions arrive as multi-choice with recommendations. `chatop accept` answers all of them.
* Turn 4: the LLM *proposes* `@@check`s, and they only become active when you approve the SPEC.
* Turn 6 onward: every slice shows `TDD red step: proven` and is committed (`git log`).
* Open `.chatop/packets/turn-0008.md` and find the decisions, history, SPEC, and the slice's ACs.
**Exercises:**
1. At the PRD gate, run `chatop reject "add an AC for empty input"` instead of approving, then `chatop next`. Find your
   note in the new packet.
2. Edit `replies/07-s1-convert.md` so its SEARCH or path is wrong, then apply it. Read the repair prompt.
3. After a slice, run `chatop undo` and see which files are restored (it refuses committed slices: use `git revert`).

## Lab 2: continue with a feature (`labs/continue-feature`)
**Goal:** the `continue` track, and the evidence loop.
**Observe:**
* `chatop feature` switches the track. The FEATURE packet still lists S0-S2 and all prior decisions.
* DELTA uses `@@edit` on the PRD/SPEC instead of rewriting them.
* Reply 13 is deliberately buggy. chatop applies it, the test fails, and turn 14's packet carries the exact assertion
  failure. Reply 14 is code-only, which is allowed because RED was already proven for this slice.
**Exercise:** in reply 14, remove the fix and change the test expectation instead. Notice that the prompt forbids
weakening tests; discuss how you would catch this at review (`git diff` of `tests/`).

## Lab 3: adopt an agent-built project (`labs/adopt`)
**Goal:** reverse-document unknown code before changing it.
**Observe:**
* `chatop init` without `--track` picks `adopt` (tests and a test command exist).
* The RECON packet contains the agent fingerprints (`claude=…`), AGENTS.md, the hotspots, and the repo map.
* Reply 2 asks a question **and** requests `todo.py` in the same turn. Both are served by the next packet.
* The DELTA creates a PRD/SPEC scoped to the feature, because the adopted project had none.
**Exercise:** with codegraph installed, rerun the lab and compare turn 1's repo map and the `@@need symbol TodoStore`
results.

## Lab 5: parallel relay, several chats at once (`labs/parallel-relay`)
**Goal:** work two issues in two chats at the same time, and see what chatop does so you do not have to.
**Setup:** `chatop init --parallel 3`; a PLAN with `depends`/`touches`: S0 → (S1 ∥ S2) → S3.
**Observe:**
* After the plan is approved only S0 is ready. When S0 is done, chatop opens two chats (**full** packets) for S1 and S2.
* Chat c2 answers first with a failing test. Nothing it wrote touches the tree (`git status` is clean).
* Chat c3 answers with **two syntax errors in two files**: one rejection lists both. Its corrected reply then passes and
  is committed, although c2's failing test exists: lanes are isolated.
* c2's next packet is a **delta**: `chatop next c2` prints about 490 tokens against about 2,480 for a full packet.
* S3 depends on S1 and S2. It goes to c2 because c2 already holds `convert.py`: another delta packet.
* `chatop board` at the end shows tokens sent versus full and the event log.
**Exercises:**
1. Run with `chatop config --set max_parallel 1` before the plan is approved and compare the number of turns waiting.
2. In `replies/07-s1-convert-bug.md` change the header to `chat=c3`. What happens to the routing? (Read the error.)
3. Open `.chatop/lanes/c2.json` after the failing reply: that is the chat's held-back work.
4. Try the mock UI (`docs/chatop-mock-ui.html`) and finish the project by pasting replies in the wrong order on purpose.

## Lab 4: audit a project of unknown quality (`labs/audit`)
**Goal:** find out what is really there, pin it with tests, then fix it.
**Observe:**
* The README claims "fully tested". Recon shows 0 test files, and the AUDIT packet shows `pytest` exit code 5.
* **Safety point:** the test command is proposed by the LLM and accepted by you (`chatop checks --accept`).
* C1 is a characterization slice: its tests pin current behavior (including the crash on decimal prices) and may
  pass immediately. The audit track allows this.
* F1 changes the pinned expectation and fixes the bug. RED is proven (the new expectation fails on the old code).
**Real-world lesson:** the first draft of this lab's reference reply assumed `int("9.99")` truncates. chatop's evidence
showed it raises `ValueError`. Characterization tests exist to replace assumptions with facts.

## Lab 5: your own project (open)
Pick a small real repo. `chatop init`. Let the track auto-detect. Do RECON (+ AUDIT) and then one feature. Track:
turns used, packets' token sizes (`chatop next` prints them), the number of repair prompts, and the slices completed
on the first attempt. That is your baseline for tuning `budget_tokens`, slice size and gates.
