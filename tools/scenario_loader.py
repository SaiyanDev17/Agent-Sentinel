"""Cached scenario loading from JSON files."""

from __future__ import annotations

import json
import os

SCENARIOS_DIR = os.path.join(os.path.dirname(__file__), "..", "scenarios")


def load_all_scenarios() -> dict:
    all_scenarios = []
    categories = {}

    if not os.path.isdir(SCENARIOS_DIR):
        return {"total_scenarios": 0, "categories": {}, "scenarios": []}

    for filename in sorted(os.listdir(SCENARIOS_DIR)):
        if not filename.endswith(".json"):
            continue
        filepath = os.path.join(SCENARIOS_DIR, filename)
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                scenarios = json.load(f)
                category_name = filename.replace(".json", "")
                categories[category_name] = len(scenarios)
                all_scenarios.extend(scenarios)
        except Exception as exc:
            categories[filename] = f"error: {exc}"

    return {
        "total_scenarios": len(all_scenarios),
        "categories": categories,
        "scenarios": all_scenarios,
    }
