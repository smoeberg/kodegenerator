from infrastructure.runtime.worker_session import job_session


class FakeSession:
    def __init__(self):
        self.rolled_back = False
        self.closed = False

    def rollback(self):
        self.rolled_back = True

    def close(self):
        self.closed = True


def test_job_session_closes_session():
    session = FakeSession()
    with job_session(lambda: session) as current:
        assert current is session
    assert session.closed is True
    assert session.rolled_back is False


def test_job_session_rolls_back_on_failure():
    session = FakeSession()
    try:
        with job_session(lambda: session):
            raise RuntimeError("worker failure")
    except RuntimeError:
        pass
    assert session.rolled_back is True
    assert session.closed is True
