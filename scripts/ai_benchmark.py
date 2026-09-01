#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPOSITORY = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPOSITORY / "src"))

from goalwatch.audit import AuditStore  # noqa: E402
from goalwatch.config import DEFAULT_CONFIG  # noqa: E402
from goalwatch.gemini import GeminiClient, GeminiError  # noqa: E402
from goalwatch.goals import Goal  # noqa: E402
from goalwatch.secrets import get_api_key  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the GoalWatch synthetic AI behavior benchmark.")
    parser.add_argument(
        "--manifest",
        type=Path,
        default=REPOSITORY / "tests" / "ai-fixtures" / "manifest.json",
    )
    parser.add_argument("--model", default=DEFAULT_CONFIG["model"])
    args = parser.parse_args()

    key = get_api_key()
    if not key:
        print("Set the GoalWatch Gemini API key before running the benchmark.", file=sys.stderr)
        return 2
    manifest_path = args.manifest.expanduser().resolve()
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    goal = Goal(str(manifest["goal"]), str(manifest["tools"]))
    cases = manifest.get("cases") or []
    if not cases:
        print("The benchmark manifest has no cases.", file=sys.stderr)
        return 2

    client = GeminiClient(key, args.model)
    true_positive = false_positive = true_negative = false_negative = errors = 0
    results = []
    with AuditStore() as audit:
        for case in cases:
            identifier = str(case["id"])
            expected = bool(case["expected_alert"])
            image_path = (manifest_path.parent / str(case["image"])).resolve()
            try:
                decision = client.classify(goal, image_path.read_bytes(), audit=audit)
                actual = decision.alert
                if expected and actual:
                    true_positive += 1
                elif expected and not actual:
                    false_negative += 1
                elif not expected and actual:
                    false_positive += 1
                else:
                    true_negative += 1
                results.append(
                    {
                        "id": identifier,
                        "expected_alert": expected,
                        "actual_alert": actual,
                        "latency_ms": decision.latency_ms,
                    }
                )
            except (GeminiError, OSError) as error:
                errors += 1
                results.append({"id": identifier, "error": str(error)})

    predicted_alerts = true_positive + false_positive
    negative_cases = true_negative + false_positive
    precision = true_positive / predicted_alerts if predicted_alerts else 0.0
    false_alert_rate = false_positive / negative_cases if negative_cases else 0.0
    passed = errors == 0 and precision >= 0.90 and false_alert_rate <= 0.05
    print(
        json.dumps(
            {
                "model": args.model,
                "cases": len(cases),
                "precision": round(precision, 4),
                "false_alert_rate": round(false_alert_rate, 4),
                "errors": errors,
                "passed": passed,
                "results": results,
            },
            indent=2,
        )
    )
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
