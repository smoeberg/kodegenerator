"""Completion plan step 8a: the first run's role assignment, setup and backup."""

from __future__ import annotations

import copy
import json

import pytest

from execution.first_run import (
    FirstRunError,
    assignment_report,
    check_config,
    environment_lines,
    load_config,
    setup,
)
from services.offsite_backup import OffsiteBackup, OffsiteBackupError


def test_the_shipped_assignment_allows_the_first_run() -> None:
    report = assignment_report(load_config())
    assert report["problems"] == []
    # Governance roles on one producer control each other only in the catalog, not in this run.
    assert all("not exercised" in w for w in report["warnings"])


def _with(change):
    config = copy.deepcopy(load_config())
    change(config)
    return config


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (
            lambda c: c["agents"]["coder"].update(brand="anthropic"),
            "test designer's producer",
        ),
        (
            lambda c: c["agents"]["coder"].update(brand="mistral"),
            "code_auditor controls coder",
        ),
        (
            lambda c: next(
                p for p in c["profiles"] if p["role"] == "architecture_reviewer"
            ).update(deployment_id="claude-opus"),
            "architecture_reviewer controls architect",
        ),
        (
            lambda c: next(
                p for p in c["profiles"] if p["role"] == "product_owner"
            ).update(deployment_id="claude-opus"),
            "product_owner judges code built by test_designer",
        ),
        (
            lambda c: c["profiles"][1].update(env=c["profiles"][0]["env"]),
            "share an environment variable",
        ),
        (
            lambda c: c["profiles"][0].update(deployment_id="ghost"),
            "unknown deployment",
        ),
        (lambda c: c["profiles"][0].update(role="ghost"), "not a role in the catalog"),
    ],
)
def test_an_unsafe_assignment_is_refused(change, message) -> None:
    assert any(message in p for p in check_config(_with(change)))


class FakeApi:
    organization_id = "org-1"

    def __init__(self, conflicts=()):
        self.calls = []
        self.conflicts = set(conflicts)

    def call(self, method, path, body=None):
        self.calls.append((method, path, body))
        if (
            any(c in path for c in self.conflicts)
            and method == "POST"
            and not path.endswith("/activate")
        ):
            return 409, {"error": "version_conflict"}
        return 201, {}


def test_setup_creates_the_catalog_and_never_shows_a_key(capsys) -> None:
    api = FakeApi(conflicts={"/connections"})
    env = {
        "ANTHROPIC_API_KEY": "sk-ant-secret-1",
        "MISTRAL_API_KEY": "mistral-secret-2",
    }
    log = setup(load_config(), api, env)
    assert "exists connection anthropic-api" in log
    assert sum(1 for line in log if line.startswith("active profile")) == 10
    credentials = [b for m, p, b in api.calls if "bot-provider-credentials" in p]
    assert [b["api_key"] for b in credentials] == [
        "sk-ant-secret-1",
        "mistral-secret-2",
    ]
    assert "secret" not in json.dumps(log)
    profiles = [b for m, p, b in api.calls if p.endswith("/profiles")]
    assert {b["budget_policy"]["max_input_tokens"] for b in profiles} == {120000}
    assert all(
        b["enabled"] is False for b in profiles
    )  # created disabled, then activated


def test_setup_needs_every_key_first() -> None:
    with pytest.raises(FirstRunError, match="MISTRAL_API_KEY"):
        setup(load_config(), FakeApi(), {"ANTHROPIC_API_KEY": "k"})


def test_environment_lines_name_every_profile() -> None:
    lines = environment_lines(load_config())
    assert "export DOR_SECURITY_REVIEWER_BOT_PROFILE=fr-security-reviewer" in lines
    assert "export DOR_CODER_AGENT=codex" in lines


class FakeBucket:
    def __init__(self, corrupt=False):
        self.objects = {}
        self.corrupt = corrupt

    def head_object(self, Bucket, Key):
        if Key not in self.objects:
            error = Exception("not found")
            error.response = {"Error": {"Code": "404"}}
            raise error
        body, meta = self.objects[Key]
        return {
            "ContentLength": len(body) - (1 if self.corrupt else 0),
            "Metadata": meta,
        }

    def put_object(self, Bucket, Key, Body, Metadata):
        self.objects[Key] = (Body.read(), dict(Metadata))


def test_offsite_backup_is_verified_and_never_overwritten(tmp_path) -> None:
    bundle = tmp_path / "M1.bundle"
    bundle.write_bytes(b"bundle")
    bucket = FakeBucket()
    backup = OffsiteBackup(bucket, "dor-backup")
    [uploaded] = backup.upload("M1", [bundle])
    assert uploaded["key"] == "dor/M1/M1.bundle" and len(uploaded["sha256"]) == 64
    with pytest.raises(OffsiteBackupError, match="never overwritten"):
        backup.upload("M1", [bundle])
    with pytest.raises(OffsiteBackupError, match="intact"):
        OffsiteBackup(FakeBucket(corrupt=True), "b").upload("M1", [bundle])


def test_offsite_backup_configuration_is_all_or_nothing(monkeypatch) -> None:
    for name in ("ENDPOINT", "BUCKET", "ACCESS_KEY", "SECRET_KEY"):
        monkeypatch.delenv(f"DOR_BACKUP_S3_{name}", raising=False)
    assert OffsiteBackup.from_environment() is None
    monkeypatch.setenv("DOR_BACKUP_S3_BUCKET", "b")
    with pytest.raises(OffsiteBackupError, match="ENDPOINT"):
        OffsiteBackup.from_environment()
