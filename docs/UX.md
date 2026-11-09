# UX of the relay: who acts next

The expensive resource in chatop is **your attention**, not the model's tokens. The web page and the mock UI are designed
around one question per chat: *whose move is it?* Everything else (tokens, plan, events) is folded away.

## The model: every chat is in exactly one stage

| Stage | Owner | What it means | The one button |
|---|---|---|---|
| `send` | you | chatop has the next packet | **Copy packet** |
| `paste` | you | packet copied; paste it in the chat window | **I pasted it ✓** |
| `fix` | you | the last reply was rejected; paste the repair prompt | **Copy repair prompt**, then **I pasted it ✓** |
| `answer` | you | the LLM asked questions | **Submit answers** / **Use recommended** |
| `blocked` | you | attempts exhausted; you decide | **Unblock** |
| `waiting` | LLM | flagged as pasted; the clock runs | *(nothing: paste the reply when it arrives)* |
| `applying` | chatop | reply routed; applying and running checks | *(nothing)* |
| `closed` | nobody | the issue is done; the chat is free and keeps its context | *(folded away)* |

The rule is the pure function `chatop.domain.stage.stage_of(status, sent_at, repair)`; the CLI (`chatop board`), TUI,
web page and the mock all show the same stage. `sent_at` is the **"I pasted it" flag**: chatop cannot see your browser
tabs, so *you* tell it (one click, or **N**). Copying a packet alone is not enough, because copying is not pasting.
The flag starts the "pasted 2:14 ago" clock, and it is cleared whenever the awaited reply changes (new packet,
rejection, apply, reset). `chatop sent c2` does the same from the terminal; `--undo` takes it back.

## Screens

1. **Projects (hub, mock only for now).** A cross-project inbox, "Your move across all projects", then one card per
   project with a progress bar, chips (`2 your move · 1 waiting 4:03 · 1 closed`) and the single next action.
   Projects that need you come first, finished ones last.
2. **Project.** A header that says in words what is going on ("2 chats need you"), one primary button that does the top
   action, a progress bar, a paste box, and two columns: **Your move** and **Waiting for the LLM**. Closed chats, the
   plan table and the events are folded away.
3. **Chat window simulator (mock only).** The side panel stands in for your browser tabs, so you can practise the
   relay, including the out-of-order and rejected-reply cases.

## UX laws applied

| Law | Where |
|---|---|
| **Hick's law**: fewer choices, faster decisions | One primary button per card and per screen; **N** does the top action; closed chats, plan and events are collapsed; secondary actions live under *More*. |
| **Fitts's law**: big, near targets | Whole project cards are click targets; the primary button is large and sits directly under the text it acts on. |
| **Jakob's law**: users expect what they know | Inbox, cards, breadcrumbs (`Projects › csv2md`), Kanban-style columns, deep links (`#notes-api`). |
| **Miller's law**: chunk information | Two columns, counts instead of lists on the hub, collapsed secondary sections. |
| **Doherty threshold**: respond within ~400 ms | Optimistic updates (the card moves the instant you click); a live clock replaces a frozen page while the LLM writes; applying shows a spinner. |
| **Zeigarnik effect**: unfinished tasks stay in mind | `paste` and `fix` (started, not finished) sort to the top of *Your move* until you complete them. |
| **Goal-gradient effect**: effort grows near the goal | "n of m issues closed" with a progress bar on every project and on the hub. |
| **Von Restorff effect**: the odd one out is remembered | Only what needs you is accent-colored (column border, count, chips); waiting and closed work stays calm. |
| **Serial position effect** | Needing-you projects first, finished last; inside a project the step to finish first is first. |
| **Tesler's law** (conservation of complexity) and **Postel's law** | You never say which chat a reply is for: paste it anywhere on the page (even with nothing focused) and chatop routes it by its header. Pasting something that is not a reply gets a precise explanation, not an error code. |
| **Peak-end rule** | A finished project says so plainly and shows the tokens saved, instead of an empty list. |
| **Aesthetic-usability / accessibility** | Visible focus rings, real buttons (keyboard reachable), `prefers-color-scheme` and `prefers-reduced-motion` honoured, status never conveyed by color alone (every stage has a text label). |

## What is real and what is mock

| | Real app | Mock only |
|---|---|---|
| Stage model, `sent_at` flag, board summary, `chatop sent`, `/api/chat/sent` | ✔ | |
| Project page: hero, columns, optimistic updates, paste anywhere, **N** shortcut, "I pasted it" | ✔ (same file) | |
| Projects hub and cross-project inbox | proposal | ✔ |
| Chat windows, scripted LLMs, seeded projects | | ✔ |

The hub needs a project registry (a list of project roots and one server per project, or one server for many); it is
deliberately not part of the app yet. See ADR-021.

## Limits worth knowing

* chatop cannot know that the LLM has *finished* writing: that happens in a tab it cannot see. The page therefore shows
  how long ago you pasted, not "reply ready". The moment you paste the reply, the card moves on by itself.
* If you forget to click "I pasted it", nothing breaks: the chat simply stays under *Your move* (as `paste`) and pasting
  its reply still routes and applies it.
