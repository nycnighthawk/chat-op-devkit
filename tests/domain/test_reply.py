"""Reply parser: the single inbound boundary from the chat LLM."""

from chatop.domain.reply import parse_reply

FULL = """Some chatter the model wrote before the block.
````chatop
<<<CHATOP turn=7>>>
@@summary Added PRD and asked about auth
@@doc docs/PRD.md
# PRD
Body with ``` fences inside is fine
@@end
@@test tests/test_calc.py
def test_add():
    assert add(1, 2) == 3
@@end
@@file src/calc.py
def add(a: int, b: int) -> int:
    return a + b
@@end
@@edit src/app.py
<<<<<<< SEARCH
old = 1
=======
old = 2
>>>>>>> REPLACE
@@end
@@delete src/legacy.py
@@ask q1
Which database?
- [x] SQLite
- [ ] Postgres
@@end
@@ask q2 single
Ship a CLI?
- [x] Yes
- [ ] No
@@end
@@need symbol Calculator
@@need callers parse_reply
@@decision Use SQLite: single user, zero ops
@@run test
@@run typecheck
@@advance
<<<END>>>
````
trailing text
"""


def test_parses_all_directives() -> None:
    r = parse_reply(FULL)
    assert r.errors == []
    assert r.turn == 7
    assert r.summary == "Added PRD and asked about auth"
    roles = {w.path: w.role for w in r.writes}
    assert roles == {"docs/PRD.md": "doc", "tests/test_calc.py": "test", "src/calc.py": "code"}
    prd = next(w for w in r.writes if w.path == "docs/PRD.md")
    assert "``` fences" in prd.content and prd.content.endswith("\n")
    assert r.edits[0].path == "src/app.py"
    assert r.edits[0].blocks == [("old = 1\n", "old = 2\n")]
    assert r.deletes == ["src/legacy.py"]
    assert [q.id for q in r.questions] == ["q1", "q2"]
    assert r.questions[0].options == ["SQLite", "Postgres"]
    assert r.questions[0].recommended == ["SQLite"]
    assert r.questions[0].multi is True and r.questions[1].multi is False
    assert r.questions[0].text == "Which database?"
    assert [(n.kind, n.target) for n in r.needs] == [("symbol", "Calculator"), ("callers", "parse_reply")]
    assert r.decisions == ["Use SQLite: single user, zero ops"]
    assert r.runs == ["test", "typecheck"]
    assert r.advance is True


def test_missing_block_is_error() -> None:
    r = parse_reply("I could not do it, sorry")
    assert r.errors and "No <<<CHATOP" in r.errors[0]


def test_truncated_reply_detected() -> None:
    r = parse_reply("<<<CHATOP turn=1>>>\n@@file a.py\nx = 1\n")
    assert any("truncated" in e for e in r.errors)


def test_unterminated_block_is_error() -> None:
    r = parse_reply("<<<CHATOP turn=1>>>\n@@file a.py\nx = 1\n<<<END>>>")
    assert any("@@end" in e for e in r.errors)


def test_unknown_directive_and_bad_need_reported() -> None:
    r = parse_reply("<<<CHATOP turn=1>>>\n@@frobnicate x\n@@need bogus y\n<<<END>>>")
    assert any("frobnicate" in e for e in r.errors)
    assert any("bogus" in e for e in r.errors)


def test_slices_json() -> None:
    text = (
        "<<<CHATOP turn=3>>>\n@@slices\n"
        '[{"id":"S1","title":"Add","goal":"g","acceptance":["AC1"],"touches":["src/calc.py"]}]\n'
        "@@end\n<<<END>>>"
    )
    r = parse_reply(text)
    assert r.errors == []
    assert r.slices is not None and r.slices[0].id == "S1" and r.slices[0].touches == ["src/calc.py"]


def test_bad_slices_json() -> None:
    r = parse_reply("<<<CHATOP turn=3>>>\n@@slices\nnot json\n@@end\n<<<END>>>")
    assert any("slices" in e for e in r.errors)


def test_crlf_input_normalised() -> None:
    r = parse_reply("<<<CHATOP turn=2>>>\r\n@@file a.py\r\nx = 1\r\n@@end\r\n<<<END>>>\r\n")
    assert r.errors == [] and r.writes[0].content == "x = 1\n"


def test_role_inference_for_file_directive() -> None:
    text = "<<<CHATOP turn=1>>>\n@@file pkg/foo_test.go\npackage pkg\n@@end\n<<<END>>>"
    assert parse_reply(text).writes[0].role == "test"


def test_check_proposal() -> None:
    r = parse_reply("<<<CHATOP turn=1>>>\n@@check test python -m pytest -q\n@@check bad\n<<<END>>>")
    assert r.checks == {"test": "python -m pytest -q"}
    assert any("@@check bad" in e for e in r.errors)


def test_packet_is_never_a_reply() -> None:
    packet = "## Role and rules\n\n# CHATOP PACKET · project x · turn 1\n<<<CHATOP turn=1>>>\n<<<END>>>\n"
    assert parse_reply(packet).errors and "PACKET" in parse_reply(packet).errors[0]
    from chatop.domain.reply import contains_envelope

    assert contains_envelope(packet) is None


def test_header_carries_chat_id_in_any_order() -> None:
    assert parse_reply("<<<CHATOP chat=c2 turn=5>>>\n<<<END>>>").chat == "c2"
    r = parse_reply("<<<CHATOP turn=5 chat=c2>>>\n<<<END>>>")
    assert (r.chat, r.turn, r.errors) == ("c2", 5, [])
    r = parse_reply("<<<CHATOP turn=5>>>\n<<<END>>>")
    assert r.chat is None and r.turn == 5


def test_envelope_header_for_routing() -> None:
    from chatop.domain.reply import envelope_header

    assert envelope_header("noise\n````chatop\n<<<CHATOP chat=c7 turn=2>>>\n<<<END>>>") == ("c7", 2)
    assert envelope_header("<<<CHATOP turn=4>>>") == (None, 4)
    assert envelope_header("# CHATOP PACKET · x\n<<<CHATOP chat=c1 turn=1>>>") is None  # a packet, never a reply
    assert envelope_header("nothing here") is None


def test_slices_may_declare_dependencies() -> None:
    text = (
        "<<<CHATOP turn=3>>>\n@@slices\n"
        '[{"id":"S1","title":"a","touches":["a.py"]},{"id":"S2","title":"b","depends":["S1"],"touches":["b.py"]}]\n'
        "@@end\n<<<END>>>"
    )
    r = parse_reply(text)
    assert r.slices is not None and r.slices[1].depends == ["S1"] and r.slices[0].depends == []
