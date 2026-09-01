from contextlib import contextmanager

import pytest

from services import runtime_readiness


class _Rows:
    def __init__(self, values):
        self._values = values

    def __iter__(self):
        return iter(self._values)


class _Session:
    def __init__(self, heads):
        self._heads = heads

    def execute(self, statement):
        if "alembic_version" in str(statement):
            return _Rows([(head,) for head in self._heads])
        return _Rows([])


class _Database:
    def __init__(self, heads):
        self._heads = heads

    @contextmanager
    def session(self):
        yield _Session(self._heads)


def test_readiness_accepts_only_the_canonical_head(monkeypatch) -> None:
    monkeypatch.setattr(runtime_readiness, "expected_alembic_head", lambda: "025")

    assert runtime_readiness.verify_database_readiness(_Database(["025"])) == "025"


@pytest.mark.parametrize("heads", [[], ["024"], ["024", "025"]])
def test_readiness_rejects_missing_stale_or_divergent_heads(monkeypatch, heads) -> None:
    monkeypatch.setattr(runtime_readiness, "expected_alembic_head", lambda: "025")

    with pytest.raises(RuntimeError, match="canonical Alembic head"):
        runtime_readiness.verify_database_readiness(_Database(heads))
