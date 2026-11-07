import json
import sys


def load(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []


def total_value(items):
    total = 0
    for it in items:
        total += int(it["price"]) * it["qty"]
    return total


def restock(items, threshold=5):
    out = []
    for it in items:
        if it["qty"] < threshold:
            out.append(it["sku"])
    return out


if __name__ == "__main__":
    data = load(sys.argv[1] if len(sys.argv) > 1 else "data.json")
    print("value:", total_value(data))
    print("restock:", ", ".join(restock(data)))
