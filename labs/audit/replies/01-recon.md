````chatop
<<<CHATOP turn=@TURN@>>>
@@summary AS-BUILT for legacy-inventory; README claims are unverified
@@doc docs/AS-BUILT.md
# As-built: legacy-inventory
## Purpose
Computes the stock value and the restock list from a JSON file.
## Architecture
One script, `inventory.py`: `load(path)`, `total_value(items)`, `restock(items, threshold=5)`, `__main__` block.
## Build / test
No test suite exists. The README's claim "fully tested" is **false** (no test files in the inventory).
## Conventions
Untyped, broad `except Exception`.
## Gaps
README vs code: no tests; `price` values are strings in data.json.
@@end
@@check test python -m pytest -q
<<<END>>>
````
