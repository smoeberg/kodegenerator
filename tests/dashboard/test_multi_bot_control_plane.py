from dashboard.multi_bot_control_plane import _get, _post


class FakeClient:
    def __init__(self):
        self.calls = []

    def get(self, path, **kwargs):
        self.calls.append(("GET", path, kwargs))
        return {"ok": True}

    def post(self, path, **kwargs):
        self.calls.append(("POST", path, kwargs))
        return {"ok": True}


def test_get_scopes_request_with_canonical_client():
    client = FakeClient()

    assert _get(client, "org-1", "/resource") == {"ok": True}
    assert client.calls == [
        ("GET", "/resource", {"params": {"organization_id": "org-1"}})
    ]


def test_post_scopes_request_and_uses_json_payload():
    client = FakeClient()
    payload = {"command_id": "cmd-1"}

    assert _post(client, "org-1", "/resource", payload) == {"ok": True}
    assert client.calls == [
        (
            "POST",
            "/resource",
            {
                "params": {"organization_id": "org-1"},
                "json": payload,
            },
        )
    ]
