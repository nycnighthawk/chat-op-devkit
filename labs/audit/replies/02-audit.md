````chatop
<<<CHATOP turn=@TURN@>>>
@@summary Audit: 1 critical money bug, error swallowing, zero tests
@@doc docs/AUDIT.md
# Audit: legacy-inventory

## Executive summary
| area | light |
|---|---|
| tests | red (pytest exit 5: no tests collected) |
| correctness | red |
| types | red (none) |
| error handling | amber |
| docs | red (README overclaims) |

## Risk register
| ID | module | finding | evidence | sev | action |
|---|---|---|---|---|---|
| R1 | inventory | `int(price)` raises ValueError on decimal strings ("9.99"): the tool crashes on its own data.json | inventory.py:total_value | critical | characterize, then fix with Decimal |
| R2 | inventory | `load` swallows every exception and returns [], so a corrupt file reports value 0 | inventory.py:load | high | characterize, then fix later |
| R3 | repo | no tests | recon: 0 test files | high | characterize |

## Test gap map
Every function is untested. The hotspot is `total_value` (money).

## Agent-artifact smells
README claims tests that do not exist.

## Stabilization order
C1 characterize all three functions → F1 fix R1 → (later) F2 fix R2.
@@end
@@advance
<<<END>>>
````
