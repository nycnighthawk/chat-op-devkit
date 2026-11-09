# source bootstrap/env.sh   (once per terminal session, from the repo root)
# `relay` = the stage-0 kernel; RELAY_CHECKS run after every applied reply (the tests always run).
relay() { python3 "$(git rev-parse --show-toplevel)/bootstrap/relay.py" "$@"; }
export RELAY_CHECKS="ruff check src tests; mypy --strict src"
[ -d .venv ] && . .venv/bin/activate
echo "relay ready: $(command -v python3); checks: $RELAY_CHECKS"
