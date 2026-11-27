"""The reference project's requirements spec must be runnable by the pipeline.

docs/plan/kravspec/husregel-register.yaml is the canonical kravspec for the
first end-to-end run (completion plan, step 1 and 8a). These checks keep it
valid for `/pipeline/start` and keep its ids traceable.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from services.pipeline_adapter import PipelineAdapter

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ROOT / "docs" / "plan" / "kravspec" / "husregel-register.yaml"
HOUSE_RULES_PATH = ROOT / "docs" / "plan" / "HUSREGLER_V1.md"
AC_PATTERN = re.compile(r"^(AC-(REG-\d{2})-\d+): \S")


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text(encoding="utf-8"))


def test_spec_is_accepted_by_the_pipeline_validator(spec: dict) -> None:
    PipelineAdapter()._validate_spec(spec)


def test_requirement_ids_are_unique_and_sequential(spec: dict) -> None:
    ids = [req["id"] for req in spec["requirements"]]
    assert len(ids) == len(set(ids))
    assert ids == [f"REG-{n:02d}" for n in range(1, len(ids) + 1)]


def test_every_criterion_has_an_id_owned_by_its_requirement(spec: dict) -> None:
    seen: set[str] = set()
    for req in spec["requirements"]:
        assert req.get("priority") in {"must", "should", "could", "wont"}, req["id"]
        for criterion in req["acceptance_criteria"]:
            match = AC_PATTERN.match(criterion)
            assert match, f"{req['id']}: criterion without id: {criterion!r}"
            assert match.group(2) == req["id"], criterion
            assert match.group(1) not in seen, f"duplicate {match.group(1)}"
            seen.add(match.group(1))


def test_import_requirement_matches_the_house_rules_draft(spec: dict) -> None:
    """AC-REG-15-1 names the rule range; it must match the draft it imports."""
    rule_ids = re.findall(
        r"^\| (\d\.\d) \|", HOUSE_RULES_PATH.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert rule_ids[0] == "1.1"
    assert rule_ids[-1] == "8.2"
    (import_req,) = [req for req in spec["requirements"] if req["id"] == "REG-15"]
    assert any("1.1 til 8.2" in c for c in import_req["acceptance_criteria"])


def test_approved_spec_has_no_open_questions_or_unconfirmed_assumptions(
    spec: dict,
) -> None:
    assert spec["status"] == "approved"
    assert spec["approved_by"] == "projektleder"
    assert spec.get("open_questions") == []
    for assumption in spec["assumptions"]:
        assert assumption["requires_confirmation"] is False, assumption["id"]
        assert assumption.get("confirmed"), assumption["id"]


def test_every_house_rule_has_type_and_a_lifecycle_state() -> None:
    rows = re.findall(
        r"^\| (\d\.\d) \| .+? \| ([MV]) \| .+? \| (Aktiv|På prøve) \|$",
        HOUSE_RULES_PATH.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    all_ids = re.findall(
        r"^\| (\d\.\d) \|", HOUSE_RULES_PATH.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert [row[0] for row in rows] == all_ids
    for rule_id, rule_type, state in rows:
        # Decision 5 at approval: every M rule starts active.
        if rule_type == "M":
            assert state == "Aktiv", rule_id
