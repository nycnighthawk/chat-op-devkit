"""Delta context for continuing chats, and the pure TDD verdict shared by serial and parallel slices."""

from chatop.domain.delta import digest, plan_delta
from chatop.domain.tdd import judge_slice


def test_digest_is_stable_and_content_sensitive() -> None:
    assert digest("a") == digest("a") and digest("a") != digest("b") and len(digest("a")) == 12


def test_plan_delta_new_changed_unchanged_and_no_stale_keys() -> None:
    seen = {"doc:A": digest("one"), "doc:B": digest("two"), "doc:OLD": digest("x")}
    current = {"doc:A": "one", "doc:B": "TWO!", "doc:C": "three"}
    d = plan_delta(seen, current)
    assert d.unchanged == ["doc:A"] and d.changed == ["doc:B", "doc:C"]
    assert d.new_seen == {"doc:A": digest("one"), "doc:B": digest("TWO!"), "doc:C": digest("three")}


def test_plan_delta_from_nothing_is_everything() -> None:
    d = plan_delta({}, {"k": "v"})
    assert d.changed == ["k"] and d.unchanged == []


def verdict(**kw):  # type: ignore[no-untyped-def]
    base = dict(
        strict=True,
        red_ok=True,
        red_already=False,
        check_codes=[0, 0],
        has_tests=True,
        has_code=True,
        advance=False,
        touched=True,
    )
    return judge_slice(**{**base, **kw})


def test_green_with_proven_red_is_done() -> None:
    v = verdict()
    assert v.done and v.red_proven and v.notes == []


def test_red_not_proven_blocks_unless_advance_or_not_strict() -> None:
    assert not verdict(red_ok=False).done and "RED not proven" in verdict(red_ok=False).notes[0]
    assert verdict(red_ok=False, advance=True).done
    assert verdict(red_ok=False, strict=False).done


def test_code_without_tests_needs_earlier_red_or_advance() -> None:
    assert not verdict(has_tests=False, red_ok=None).done
    assert verdict(has_tests=False, red_ok=None, red_already=True).done
    assert verdict(has_tests=False, red_ok=None, advance=True).done


def test_failing_or_missing_checks_never_complete() -> None:
    assert not verdict(check_codes=[0, 1]).done
    v = verdict(check_codes=[])
    assert not v.done and any("No checks configured" in n for n in v.notes)
    assert not verdict(touched=False).done
