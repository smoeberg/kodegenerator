import json
from pathlib import Path

from jsonschema import Draft202012Validator


def test_governance_bootstrap_example_conforms_to_schema() -> None:
    root = Path(__file__).parents[2]
    schema = json.loads((root / "docs/schemas/governance-bootstrap-v1.schema.json").read_text())
    example = json.loads((root / "docs/schemas/examples/governance-bootstrap-v1.example.json").read_text())
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(example)
