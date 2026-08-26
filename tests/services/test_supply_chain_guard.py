import json

from services.supply_chain_guard import SupplyChainGuard


def test_detects_aws_pat_and_rsa_private_key():
    patch = """diff --git a/config.py b/config.py
+++ b/config.py
+AWS_ACCESS_KEY_ID = \"AKIA1234567890ABCDEF\"
+GITHUB_TOKEN = \"ghp_123456789012345678901234567890123456\"
+key = \"-----BEGIN RSA PRIVATE KEY-----\"
"""
    report = SupplyChainGuard().scan_patch(patch)
    assert {f.kind for f in report.findings} >= {"aws_access_key", "github_token", "private_key"}
    assert not report.safe
    assert all("1234567890ABCDEF" not in f.evidence for f in report.findings)


def test_normal_code_has_no_secret_false_positive():
    patch = """+++ b/services/example.py
+def get_token(client):
+    return client.token_name
+def add(a, b):
+    return a + b
"""
    assert SupplyChainGuard().scan_patch(patch).safe


def test_audit_flags_vulnerable_and_passes_fixed_version(tmp_path):
    manifest = tmp_path / "requirements.txt"
    manifest.write_text("requests==2.31.0\n", encoding="utf-8")
    report = SupplyChainGuard().audit_dependencies(manifest)
    assert report.findings
    assert report.findings[0].cve == "CVE-2024-35195"

    manifest.write_text("requests==2.32.0\n", encoding="utf-8")
    assert SupplyChainGuard().audit_dependencies(manifest).safe


def test_sbom_contains_top_level_service_imports(tmp_path):
    services = tmp_path / "services"
    services.mkdir()
    (services / "one.py").write_text("import requests\nfrom cryptography import x509\n", encoding="utf-8")
    (services / "two.py").write_text("import json\nimport boto3\n", encoding="utf-8")

    sbom = SupplyChainGuard(tmp_path).generate_sbom()
    names = {component["name"] for component in sbom.components}
    assert {"requests", "cryptography", "boto3"}.issubset(names)
    assert "json" not in names
    assert json.loads(sbom.to_json())["components"] == sbom.components
