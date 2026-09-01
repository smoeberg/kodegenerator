from pathlib import Path
from types import SimpleNamespace

from scripts import bootstrap_artifact_store, worker_healthcheck


def test_artifact_bootstrap_creates_missing_bucket(monkeypatch) -> None:
    created: list[str] = []

    class MissingBucketError(Exception):
        def __init__(self) -> None:
            self.response = {"Error": {"Code": "404", "Message": "missing"}}
            super().__init__("missing")

    class FakeClient:
        def head_bucket(self, *, Bucket: str) -> None:
            raise MissingBucketError

        def create_bucket(self, *, Bucket: str) -> None:
            created.append(Bucket)

    monkeypatch.setenv("ARTIFACT_STORE_URL", "http://minio:9000")
    monkeypatch.setenv("ARTIFACT_BUCKET", "dor-artifacts")
    monkeypatch.setattr(
        bootstrap_artifact_store, "_client", lambda endpoint: FakeClient()
    )

    bootstrap_artifact_store.main()

    assert created == ["dor-artifacts"]


def test_artifact_bootstrap_preserves_existing_bucket(monkeypatch) -> None:
    class FakeClient:
        def head_bucket(self, *, Bucket: str) -> None:
            assert Bucket == "dor-artifacts"

        def create_bucket(self, *, Bucket: str) -> None:
            raise AssertionError(f"unexpected create for {Bucket}")

    monkeypatch.setenv("ARTIFACT_STORE_URL", "http://minio:9000")
    monkeypatch.setenv("ARTIFACT_BUCKET", "dor-artifacts")
    monkeypatch.setattr(
        bootstrap_artifact_store, "_client", lambda endpoint: FakeClient()
    )

    bootstrap_artifact_store.main()


def test_worker_healthcheck_requires_worker_pid_and_database(monkeypatch) -> None:
    executed: list[str] = []

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *args) -> None:
            return None

        def execute(self, statement) -> None:
            executed.append(str(statement))

    engine = SimpleNamespace(connect=lambda: Connection(), dispose=lambda: None)
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://dor@postgres/dor")
    monkeypatch.setattr(
        Path, "read_bytes", lambda self: b"python\x00-m\x00services.worker_agent\x00"
    )
    monkeypatch.setattr(worker_healthcheck, "create_engine", lambda *a, **k: engine)

    worker_healthcheck.main()

    assert executed == ["SELECT 1"]


def test_demo_environment_template_covers_contract_configuration() -> None:
    root = Path(__file__).parents[2]
    contract = __import__("json").loads(
        (root / "ci/manifests/demo_installation_contract.json").read_text()
    )
    configured = {
        line.split("=", 1)[0]
        for line in (root / ".env.demo.example").read_text().splitlines()
        if line and not line.startswith("#") and "=" in line
    }

    assert set(contract["required_configuration"]) <= configured
