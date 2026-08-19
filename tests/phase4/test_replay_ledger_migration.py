from pathlib import Path


def test_replay_ledger_migration_is_head_009():
    path = Path(__file__).parents[2] / "alembic" / "versions" / "009_p4_01_execution_replay_ledger.py"
    text = path.read_text(encoding="utf-8")
    assert 'revision = "009_p4_01_execution_replay_ledger"' in text
    assert 'down_revision = "008_phase7_runtime_queue"' in text
    assert '"execution_replay_ledger"' in text
    assert '"lease_expires_at"' in text
    assert '"fencing_token"' in text
