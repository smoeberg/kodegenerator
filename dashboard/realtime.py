"""Workflow-scoped realtime transport for the Streamlit DOR cockpit.

WebSocket is the primary transport. SSE is used only when WebSocket cannot be
established. A short-lived HttpOnly stream-session cookie is obtained through
the authenticated API client, so credentials are never placed in a stream URL.

The transport runs outside Streamlit's script thread and publishes immutable
event envelopes to a bounded queue. The UI drains that queue during a
Streamlit fragment rerun; those reruns do not poll the API.
"""
from __future__ import annotations

import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlparse, urlunparse

import requests


@dataclass(frozen=True)
class RealtimeEvent:
    event_type: str
    payload: dict[str, Any]


class WorkflowRealtime:
    """Own one workflow-scoped WebSocket/SSE connection at a time."""

    def __init__(
        self,
        api_client: Any,
        workflow_id: str,
        on_event: Callable[[RealtimeEvent], None] | None = None,
        queue_size: int = 256,
        max_reconnects: int = 5,
    ) -> None:
        self.api_client = api_client
        self.workflow_id = workflow_id
        self.on_event = on_event
        self.events: queue.Queue[RealtimeEvent] = queue.Queue(maxsize=queue_size)
        self.max_reconnects = max_reconnects
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._session_ready = False
        self._status = "offline"
        self._status_lock = threading.Lock()

    @property
    def status(self) -> str:
        with self._status_lock:
            return self._status

    def _set_status(self, value: str) -> None:
        with self._status_lock:
            self._status = value

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._set_status("connecting")
        self._thread = threading.Thread(target=self._run, name=f"dor-realtime-{self.workflow_id}", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        try:
            self.api_client.delete_stream_session(self.workflow_id)
        except Exception:
            pass
        thread = self._thread
        if thread and thread.is_alive():
            thread.join(timeout=2.0)
        self._thread = None
        self._set_status("offline")

    def drain(self, limit: int = 50) -> list[RealtimeEvent]:
        result: list[RealtimeEvent] = []
        for _ in range(limit):
            try:
                result.append(self.events.get_nowait())
            except queue.Empty:
                break
        return result

    def _publish(self, event_type: str, payload: dict[str, Any]) -> None:
        event = RealtimeEvent(event_type=event_type, payload=dict(payload))
        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass
            try:
                self.events.put_nowait(event)
            except queue.Full:
                pass
        if self.on_event is not None:
            try:
                self.on_event(event)
            except Exception:
                pass

    def _run(self) -> None:
        try:
            self.api_client.create_stream_session(self.workflow_id)
            self._session_ready = True
        except Exception:
            self._set_status("unauthorized")
            return

        delay = 0.5
        reconnects = 0
        while not self._stop.is_set():
            try:
                self._set_status("connecting")
                self._run_websocket()
                reconnects = 0
                delay = 0.5
            except Exception:
                if self._stop.is_set():
                    break
                reconnects += 1
                if reconnects > self.max_reconnects:
                    self._set_status("offline")
                    return
                self._set_status("reconnecting")
                self._stop.wait(delay)
                delay = min(delay * 2, 8.0)
                continue

            if self._stop.is_set():
                break
            # A clean WebSocket close is still a transport failure for the
            # client: immediately try the documented SSE fallback.
            try:
                self._run_sse()
                reconnects = 0
                delay = 0.5
            except Exception:
                if self._stop.is_set():
                    break
                reconnects += 1
                if reconnects > self.max_reconnects:
                    self._set_status("offline")
                    return
                self._set_status("reconnecting")
                self._stop.wait(delay)
                delay = min(delay * 2, 8.0)

    def _run_websocket(self) -> None:
        try:
            import websocket
        except ImportError as exc:
            raise RuntimeError("websocket-client is required for DOR realtime") from exc

        url = self.api_client.stream_url(self.workflow_id, websocket=True)
        cookie = self.api_client.session.cookies.get("eiraos_execution_stream")
        if not cookie:
            raise RuntimeError("stream session cookie was not created")

        self._set_status("websocket")
        ws = websocket.create_connection(
            url,
            cookie=f"eiraos_execution_stream={cookie}",
            timeout=15,
        )
        try:
            ws.settimeout(1.0)
            while not self._stop.is_set():
                try:
                    raw = ws.recv()
                except Exception as exc:
                    if self._stop.is_set():
                        return
                    if exc.__class__.__name__ in {"WebSocketTimeoutException", "TimeoutError"}:
                        continue
                    raise
                if raw is None:
                    raise RuntimeError("WebSocket closed")
                message = json.loads(raw)
                event_type = str(message.get("event_type", "message"))
                self._publish(event_type, message)
        finally:
            try:
                ws.close()
            except Exception:
                pass

    def _run_sse(self) -> None:
        url = self.api_client.stream_url(self.workflow_id, websocket=False)
        self._set_status("sse")
        with self.api_client.session.get(
            url,
            headers=self.api_client._headers(),
            stream=True,
            timeout=(15, 30),
        ) as response:
            if response.status_code == 401:
                raise RuntimeError("SSE session expired")
            response.raise_for_status()
            event_type = "message"
            data_lines: list[str] = []
            for raw_line in response.iter_lines(decode_unicode=True):
                if self._stop.is_set():
                    return
                line = raw_line or ""
                if line.startswith("event:"):
                    event_type = line[6:].strip() or "message"
                elif line.startswith("data:"):
                    data_lines.append(line[5:].lstrip())
                elif line == "" and data_lines:
                    raw_data = "\n".join(data_lines)
                    payload = json.loads(raw_data)
                    self._publish(event_type, payload)
                    event_type = "message"
                    data_lines = []


def websocket_url(http_url: str) -> str:
    parsed = urlparse(http_url)
    scheme = "wss" if parsed.scheme == "https" else "ws"
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
