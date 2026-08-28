"""Generate executable HTTP contract tests with requirement traceability."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from generation.contract_generator import GeneratedContracts


@dataclass(frozen=True)
class GeneratedTestSuite:
    path: str
    content: str
    covered_criteria: tuple[str, ...]
    fingerprint: str


class ContractTestGenerator:
    """Render pytest cases for every operation in a generated OpenAPI contract."""

    def generate(self, contracts: GeneratedContracts) -> GeneratedTestSuite:
        cases: list[str] = []
        covered: list[str] = []
        for path, operations in sorted(contracts.openapi["paths"].items()):
            for method, operation in sorted(operations.items()):
                criterion = operation["x-criterion-id"]
                status = next(iter(operation["responses"]))
                test_name = f"test_{operation['operationId']}"
                cases.append(
                    f"def {test_name}(http_client):\n"
                    "    response = http_client.request("
                    f"{method.upper()!r}, {path!r})\n"
                    f"    assert response.status_code == {int(status)}\n"
                )
                covered.append(criterion)
        content = (
            '"""Generated requirement-traceable HTTP contract tests."""\n\n'
            "import os\n\nimport httpx\nimport pytest\n\n\n"
            "@pytest.fixture\n"
            "def http_client():\n"
            "    base_url = os.environ['SYSTEM_UNDER_TEST_URL']\n"
            "    with httpx.Client(base_url=base_url, timeout=10.0) as client:\n"
            "        yield client\n\n\n"
            + "\n\n".join(cases)
            + "\n"
        )
        return GeneratedTestSuite(
            "tests/generated/test_http_contract.py",
            content,
            tuple(covered),
            hashlib.sha256(content.encode()).hexdigest(),
        )
