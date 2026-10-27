"""Validate a graph client's observed state before acknowledging delivery."""
from __future__ import annotations

import hashlib
import json

from threaddesk.services.graph_views import validate_state


def observe(expected, observed):
    expected, observed = validate_state(expected), validate_state(observed)
    matched = (all(abs(expected["camera"][key] - observed["camera"][key]) <= 1e-5 for key in ("x", "y", "scale"))
               and expected["filters"] == observed["filters"]
               and set(expected["selection"]) == set(observed["selection"]))
    for identity, point in expected["positions"].items():
        actual = observed["positions"].get(identity)
        if (actual is None or abs(point["x"] - actual["x"]) > 1e-5 or abs(point["y"] - actual["y"]) > 1e-5
                or bool(point.get("fixed")) != bool(actual.get("fixed"))):
            matched = False
            break
    digest = hashlib.sha256(json.dumps(observed, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    return {"matched": matched, "observed_digest": digest,
            "observed_nodes": len(observed["positions"]), "observed_selection": observed["selection"]}
