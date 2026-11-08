from chatop.app.config import Config


def test_parallel_defaults_keep_classic_serial_flow() -> None:
    c = Config()
    assert (c.max_parallel, c.max_attempts, c.max_issues_per_chat) == (1, 4, 3)
    assert c.auto_dispatch and c.delta_packets and c.preflight == {}


def test_roundtrip_including_preflight_globs() -> None:
    c = Config(max_parallel=3, preflight={"*.py": "ruff check {files}", "src/*.ts": "tsc --noEmit"})
    c.checks = {"test": "pytest -q"}
    back = Config.from_toml(c.to_toml())
    assert back.max_parallel == 3 and back.preflight == c.preflight and back.checks == c.checks


def test_set_option_coerces_types() -> None:
    c = Config()
    c.set_option("max_parallel", "3")
    c.set_option("delta_packets", "false")
    assert c.max_parallel == 3 and c.delta_packets is False
    import pytest

    with pytest.raises(KeyError):
        c.set_option("nope", "1")
    with pytest.raises(ValueError):
        c.set_option("max_parallel", "0")
