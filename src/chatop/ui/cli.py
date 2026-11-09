"""`chatop` command line. A thin shell: parse args -> call Session -> print. No business logic here."""

from __future__ import annotations

import argparse
import json
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from chatop.app.session import ApplyResult, PacketResult, Session, SessionError
from chatop.domain.models import Track

SessionFactory = Callable[[Path], Session]


def _default_factory(root: Path) -> Session:
    from chatop.app.wiring import build_session

    return build_session(root)


def _print_packet(p: PacketResult) -> None:
    where = "copied to clipboard" if p.copied else f"saved to {p.path} (clipboard unavailable)"
    if p.chat:
        saved = (
            f" (a full packet would be ~{p.full_tokens:,})" if p.kind == "delta" and p.full_tokens > p.tokens else ""
        )
        print(f"packet for chat {p.chat}, turn {p.turn}, {p.kind}: ~{p.tokens:,} tokens{saved}, {where}")
    else:
        print(f"packet turn {p.turn}: ~{p.tokens:,} tokens, {where}")
    for n in p.notes:
        print(f"  note: {n}")
    if p.chat:
        print(f"  -> paste it into chat {p.chat}; replies can be pasted back in any order (chatop apply / watch)")
    else:
        print("  -> paste it into your chat, then copy the reply and run: chatop apply")


def _print_apply(r: ApplyResult, s: Session) -> None:
    if not r.ok:
        n = len(r.errors)
        print(f"REJECTED. Nothing was changed ({n} problem{'s' if n != 1 else ''}, all reported at once):")
        for e in r.errors:
            print(f"  - {e}")
        print("A repair prompt was copied to the clipboard; paste it in the same chat.")
        return
    if r.chat:
        print(f"  routed to chat {r.chat}")
    for change in r.changes:
        print(f"  {change}")
    if r.red_ok is not None:
        print(f"  TDD red step: {'proven (tests failed before code)' if r.red_ok else 'NOT proven'}")
    for c in r.checks:
        print(f"  check {c.name}: {'PASS' if c.code == 0 else 'FAIL'} ({c.seconds}s)")
    for m in r.messages:
        print(f"  {m}")
    for q in s.pending_questions():
        mode = "pick one" if not q.multi else "pick any"
        print(f"\n  [{q.id}] {q.text} ({mode})")
        for o in q.options:
            print(f"     {'*' if o in q.recommended else ' '} {o}")
    if s.pending_questions():
        print("\n  answer: chatop answer <id> <choice...> [--other TEXT]  |  accept recommended: chatop accept")
    if r.next_packet:
        _print_packet(r.next_packet)
    else:
        print(f"status: {r.status}. {s.status()['hint']}")


def _print_board(b: dict[str, Any]) -> None:
    print(
        f"mode {b['mode']} · max_parallel {b['max_parallel']} · phase {b['phase']} · "
        f"tokens sent {b['tokens']['sent']:,}"
        f" (full packets would be {b['tokens']['full']:,}, saved {b['tokens']['saved']:,})"
    )
    for c in b["chats"]:
        flag = {
            "send": "SEND",
            "paste": "PASTE IT",
            "fix": "FIX",
            "answer": "ANSWER",
            "blocked": "BLOCKED",
            "waiting": "waiting",
            "applying": "applying",
            "closed": "closed",
        }[c["stage"]]
        print(
            f"  {c['id']}  {flag:<9} turn {c['turn']:<2} {c['title'] or '(no issue)'}"
            + (f"  [{c['kind']} packet]" if c["can_send"] else "")
        )
    sm = b["summary"]
    print(
        f"  your move: {sm['your_move']} · waiting for the LLM: {sm['waiting']} · closed: {sm['closed']} · "
        f"issues {sm['issues_done']}/{sm['issues_total']}"
    )
    for i in b["issues"]:
        wait = f"  waits for {', '.join(i['waiting_on'])}" if i["waiting_on"] and i["status"] == "todo" else ""
        print(f"    {i['id']:<8} {i['status']:<8} {i['title']}{wait}")
    for e in b["events"][-5:]:
        print(f"  [{e['ts']}] {e['kind']}: {e['text']}")
    print(f"next: {b['hint']}")


def _read_reply(arg: str | None, s: Session) -> str:
    if arg == "-":
        return sys.stdin.read()
    if arg:
        return Path(arg).read_text(encoding="utf-8")
    text = s.clipboard.paste()
    if not text:
        raise SessionError("clipboard is empty: copy the LLM reply first, or pass a file / '-' for stdin")
    return text


def _interactive_answers(s: Session, chat: str | None = None) -> None:
    for q in s.pending_questions(chat):
        print(f"[{q.id}] {q.text}")
        for i, o in enumerate(q.options, 1):
            print(f"  {i}. {o}{'  (recommended)' if o in q.recommended else ''}")
        raw = input("  choice numbers (comma separated, Enter = recommended): ").strip()
        picks = [q.options[int(x) - 1] for x in raw.split(",") if x.strip().isdigit()] if raw else q.recommended
        other = input("  other / extra notes (optional): ").strip()
        s.answer(q.id, picks, other, chat)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="chatop", description="Copy/paste harness for chat-LLM software development.")
    p.add_argument("-C", "--root", default=".", help="project root (default: current directory)")
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("init", help="start managing a project")
    i.add_argument("--track", choices=[t.value for t in Track if t != Track.CONTINUE])
    i.add_argument("--idea", default="")
    i.add_argument("--idea-file")
    i.add_argument("--parallel", type=int, metavar="N", help="work N chats at once (default 1 = serial)")
    st = sub.add_parser("status", help="where am I and what next")
    st.add_argument("--json", action="store_true")
    n = sub.add_parser("next", help="build the next packet and copy it to the clipboard")
    n.add_argument("chat", nargs="?", help="parallel mode: packet for this chat (default: the next one up)")
    n.add_argument("--full", action="store_true", help="send the full context (fresh browser tab / lost history)")
    n.add_argument("--accept", action="store_true", help="accept recommended answers first")
    n.add_argument("--approve", action="store_true", help="approve the gated phase first")
    n.add_argument("--print", action="store_true", help="also print the packet to stdout")
    n.add_argument("--no-clip", action="store_true")
    a = sub.add_parser("apply", help="apply the LLM reply (clipboard by default)")
    a.add_argument("source", nargs="?", help="file path, or '-' for stdin")
    a.add_argument("--force", action="store_true")
    w = sub.add_parser("watch", help="clipboard ping-pong: auto-apply replies, auto-copy next packets")
    w.add_argument("--interval", type=float, default=1.0)
    an = sub.add_parser("answer", help="answer a pending question (no args = interactive)")
    an.add_argument("qid", nargs="?")
    an.add_argument("choices", nargs="*")
    an.add_argument("--other", default="")
    an.add_argument("--chat", help="parallel mode: the chat that asked")
    ac = sub.add_parser("accept", help="accept the recommended answers for all pending questions")
    ac.add_argument("--chat", help="parallel mode: only this chat's questions")
    bd = sub.add_parser("board", help="parallel mode: chats, issues, events")
    bd.add_argument("--json", action="store_true")
    sub.add_parser("dispatch", help="hand ready issues to chats (opens new chats or reuses free ones)")
    asg = sub.add_parser("assign", help="give an issue to a free chat (or a new one)")
    asg.add_argument("issue")
    asg.add_argument("--chat")
    rc = sub.add_parser("reset-chat", help="unblock a chat / you opened a fresh tab: next packet is a full one")
    rc.add_argument("chat")
    sn = sub.add_parser("sent", help="flag that you pasted a chat's packet (or repair prompt) into its window")
    sn.add_argument("chat")
    sn.add_argument("--undo", action="store_true", help="take the flag back")
    cf = sub.add_parser("config", help="show or change options (max_parallel, max_attempts, ...)")
    cf.add_argument("--set", nargs=2, metavar=("KEY", "VALUE"))
    ap = sub.add_parser("approve", help="approve a gated phase (also accepts proposed checks)")
    ap.add_argument("--note", default="")
    rj = sub.add_parser("reject", help="send a gated phase back with a note")
    rj.add_argument("note")
    f = sub.add_parser("feature", help="start a new feature on a finished project")
    f.add_argument("text")
    f.add_argument("--force", action="store_true")
    c = sub.add_parser("checks", help="show / accept / set check commands")
    c.add_argument("--accept", action="store_true")
    c.add_argument("--set", nargs=2, metavar=("NAME", "CMD"))
    c.add_argument("--unset", metavar="NAME")
    sub.add_parser("undo", help="revert the last applied (uncommitted) reply")
    sub.add_parser("doctor", help="check the environment")
    sub.add_parser("tui", help="terminal UI")
    wb = sub.add_parser("web", help="web UI on localhost")
    wb.add_argument("--port", type=int, default=8765)
    wb.add_argument("--host", default="127.0.0.1")
    return p


def main(argv: Sequence[str] | None = None, session_factory: SessionFactory = _default_factory) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root)
    s = session_factory(root)
    try:
        return _dispatch(args, s, root, session_factory)
    except SessionError as exc:
        print(f"chatop: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


def _dispatch(args: argparse.Namespace, s: Session, root: Path, factory: SessionFactory) -> int:
    cmd = args.cmd
    if cmd == "init":
        idea = Path(args.idea_file).read_text() if args.idea_file else args.idea
        st = s.init(Track(args.track) if args.track else None, idea)
        if args.parallel:
            s.configure("max_parallel", str(args.parallel))
        print(f"initialised: track {st.track.value}, phase {st.phase.value}")
        print(f"checks: {s.config.checks or '(none yet; the LLM will propose them)'}")
        if st.track == Track.NEW and not idea:
            print("edit docs/IDEA.md, then run: chatop next")
        else:
            print("next: chatop next   (or: chatop watch)")
    elif cmd == "status":
        info = s.status()
        if args.json:
            print(json.dumps(info, indent=2, default=str))
        else:
            cur = info["slice"]
            print(
                f"{info['project']}: track {info['track']} · phase {info['phase']} · {info['status']} · "
                f"turn {info['turn']}" + (f" · slice {cur['id']} (attempt {cur['attempts'] + 1})" if cur else "")
            )
            done = sum(1 for x in info["slices"] if x["status"] == "done")
            if info["slices"]:
                print(f"slices: {done}/{len(info['slices'])} done")
            if info["chats"]:
                print("chats: " + ", ".join(f"{c['id']} {c['status']}" for c in info["chats"]))
            print(f"next: {info['hint']}")
    elif cmd == "next":
        if args.accept:
            s.accept_recommended()
        if args.approve:
            s.approve()
        p = s.build_packet(copy_to_clipboard=not args.no_clip, chat=args.chat, full=args.full)
        if args.print:
            print(p.text)
        _print_packet(p)
    elif cmd == "apply":
        r = s.apply(_read_reply(args.source, s), force=args.force)
        _print_apply(r, s)
        return 0 if r.ok else 1
    elif cmd == "watch":
        return _watch(s, args.interval)
    elif cmd == "answer":
        if args.qid:
            s.answer(args.qid, args.choices, args.other, args.chat)
        else:
            _interactive_answers(s, args.chat)
        print(f"status: {s.state.status.value}. {s.status()['hint']}")
    elif cmd == "accept":
        s.accept_recommended(args.chat)
        print(f"accepted recommended answers. {s.status()['hint']}")
    elif cmd == "approve":
        st = s.approve(args.note)
        print(f"approved. now phase {st.phase.value}. next: chatop next")
    elif cmd == "reject":
        s.reject(args.note)
        print("sent back. next: chatop next")
    elif cmd == "feature":
        s.feature(args.text, force=args.force)
        print("feature started. next: chatop next")
    elif cmd == "checks":
        if args.accept:
            print(f"accepted: {s.accept_checks()}")
        if args.set:
            s.set_check(args.set[0], args.set[1])
        if args.unset:
            s.set_check(args.unset, None)
        print(json.dumps({"configured": s.config.checks, "proposed": s.state.proposed_checks}, indent=2))
    elif cmd == "board":
        b = s.board()
        print(json.dumps(b, indent=2, default=str)) if args.json else _print_board(b)
    elif cmd == "dispatch":
        out = s.dispatch()
        for a in out:
            print(
                f"issue {a.issue} -> chat {a.chat} "
                f"({'continues, delta packet' if a.reused else 'new chat, full packet'})"
            )
        if not out:
            print("nothing to dispatch (no free capacity, or nothing is unblocked)")
        print(f"next: {s.board()['hint']}")
    elif cmd == "assign":
        a = s.assign(args.issue, args.chat)
        print(f"issue {a.issue} -> chat {a.chat}")
    elif cmd == "reset-chat":
        s.reset_chat(args.chat)
        print(f"chat {args.chat} reset: its next packet carries the full context")
    elif cmd == "sent":
        s.mark_sent(args.chat, sent=not args.undo)
        print(f"chat {args.chat}: " + ("waiting for the LLM's reply" if not args.undo else "flag removed"))
    elif cmd == "config":
        if args.set:
            print(json.dumps(s.configure(args.set[0], args.set[1])))
        else:
            print(s.config.to_toml())
    elif cmd == "undo":
        print("restored: " + ", ".join(s.undo()))
    elif cmd == "doctor":
        for name, ok, detail in s.doctor():
            print(f"[{'ok' if ok else '!!'}] {name}: {detail}")
    elif cmd == "tui":
        from chatop.ui.tui import ChatopApp

        ChatopApp(lambda: s).run()
    elif cmd == "web":
        import uvicorn

        from chatop.ui.web import create_app

        print(f"chatop web UI: http://{args.host}:{args.port}")
        uvicorn.run(create_app(lambda: s), host=args.host, port=args.port, log_level="warning")
    return 0


def _watch(s: Session, interval: float) -> int:
    print(f"watching the clipboard ({s.clipboard.name}). Ctrl+C to stop.")
    if s.state.status.value == "ready":
        _print_packet(s.build_packet())
    last: str | None = s.clipboard.paste()
    while True:
        last, result = s.watch_tick(last)
        if result is not None:
            _print_apply(result, s)
            if result.next_packet is not None:
                last = result.next_packet.text
            elif result.repair_prompt:
                last = result.repair_prompt
        time.sleep(interval)


if __name__ == "__main__":
    raise SystemExit(main())
