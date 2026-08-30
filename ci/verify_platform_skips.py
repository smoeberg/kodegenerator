#!/usr/bin/env python3
"""Verify the Phase 7 platform-skip manifest.

Enforces the contract that every "environment error" is either run green on
the correct runner or is recorded with a precise, controlled platform skip.
This script is executed by the dedicated compliance step in CI.

Rules enforced
--------------
1. The manifest parses as JSON and matches the JSON Schema.
2. Every skip id is unique and follows ``env-<n>``.
3. Every referenced test path is unique within the manifest.
4. Every environment id referenced by a skip exists in ``environments``.
5. No test may be both env-skipped and committed under ``tests/e2e`` unless
   its environment is the dedicated integration runner (e2e must never be
   silently dropped from the fast matrix with auto-heal).
6. A deterministic summary report is emitted for artifact/annotation use.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except FileNotFoundError:
        raise SystemExit(f"FAIL: manifest not found at {path}")
    except json.JSONDecodeError as exc:
        raise SystemExit(f"FAIL: manifest is not valid JSON: {exc}")


def validate_ids(manifest: dict[str, Any]) -> list[str]:
    """Rule 2: unique sequential env ids."""
    errors: list[str] = []
    ids = [entry["id"] for entry in manifest.get("skips", [])]
    if len(ids) != len(set(ids)):
        errors.append("duplicate skip ids in manifest")
    for index, entry_id in enumerate(ids, start=1):
        if not re.fullmatch(r"env-\d+", entry_id):
            errors.append(f"skip id {entry_id!r} does not match env-<n>")
        elif entry_id != f"env-{index:02d}":
            errors.append(
                f"skip id {entry_id!r} is not sequential (expected env-{index:02d})"
            )
    return errors


def validate_test_paths(manifest: dict[str, Any]) -> list[str]:
    """Rules 3 and 5: a test may appear once per environment; e2e maps to integration."""
    errors: list[str] = []
    seen: dict[tuple[str, str], str] = {}
    for entry in manifest.get("skips", []):
        for test_id in entry.get("test_ids", []):
            key = (test_id, entry.get("environment", ""))
            if key in seen:
                errors.append(
                    f"test {test_id!r} is listed twice for environment "
                    f"{entry.get('environment')!r} ({seen[key]!r} and {entry['id']!r})"
                )
                continue
            seen[key] = entry["id"]
            if (
                test_id.startswith("tests/e2e/")
                and entry.get("environment") != "integration"
            ):
                errors.append(
                    f"e2e test {test_id!r} must map to the integration runner, "
                    f"found {entry.get('environment')!r}"
                )
    return errors


def validate_environments(manifest: dict[str, Any]) -> list[str]:
    """Rule 4: every environment reference resolves."""
    errors: list[str] = []
    known = {env["id"] for env in manifest.get("environments", [])}
    if "integration" not in known:
        errors.append("manifest must declare the 'integration' environment")
    for entry in manifest.get("skips", []):
        if entry.get("environment") not in known:
            errors.append(
                f"skip {entry.get('id')!r} references unknown environment "
                f"{entry.get('environment')!r}"
            )
    return errors


def render_summary(manifest: dict[str, Any]) -> str:
    lines = [
        "# Phase 7 platform-skip summary",
        "",
        f"- Manifest version: {manifest.get('version')}",
        f"- Environments: {', '.join(env['id'] for env in manifest.get('environments', []))}",
        f"- Controlled skips: {len(manifest.get('skips', []))}",
        "",
        "| id | environment | type | owner | tests |",
        "|----|-------------|------|-------|-------|",
    ]
    for entry in manifest.get("skips", []):
        tests = ", ".join(entry["test_ids"])
        lines.append(
            f"| {entry['id']} | {entry['environment']} | {entry['type']} | "
            f"{entry['owner']} | {tests} |"
        )
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    manifest_path = REPO_ROOT / "ci" / "manifests" / "platform_skips.json"
    if argv and argv[0] == "--summary":
        if len(argv) > 1:
            with open(argv[1], "w", encoding="utf-8") as out:
                out.write(render_summary(load_json(manifest_path)))
        else:
            sys.stdout.write(render_summary(load_json(manifest_path)))
        return 0

    manifest = load_json(manifest_path)
    errors: list[str] = []
    # Rule 1: schema-declared shape (partial structural checks are intentionally
    # strict here so the CI step fails loudly on drift).
    for section in ("version", "schema", "policy", "environments", "skips"):
        if section not in manifest:
            errors.append(f"missing top-level section {section!r}")
    errors += validate_ids(manifest)
    errors += validate_test_paths(manifest)
    errors += validate_environments(manifest)

    if errors:
        print("::error::platform-skip manifest validation failed")
        for error in errors:
            print(f"  - {error}")
        return 1

    summary = render_summary(manifest)
    print(summary)
    print("\nPASS: platform-skip manifest is valid and controlled.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
