import asyncio, hashlib, hmac, json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
import pytest
from services.webhook_dispatcher import WebhookDispatcher

class Handler(BaseHTTPRequestHandler):
    responses=[]; requests=[]
    def do_POST(self):
        n=int(self.headers.get("Content-Length",0)); body=self.rfile.read(n); self.__class__.requests.append((body,self.headers.get("X-Swarm-Signature")))
        code=self.__class__.responses.pop(0) if self.__class__.responses else 200; self.send_response(code); self.end_headers()
    def log_message(self,*args): pass

def server():
    http=HTTPServer(("127.0.0.1",0),Handler); Thread(target=http.serve_forever,daemon=True).start(); return http

@pytest.mark.asyncio
async def test_successful_hmac_dispatch():
    Handler.responses=[]; Handler.requests=[]; s=server(); d=WebhookDispatcher(timeout=1,base_delay=0)
    d.register("a",f"http://127.0.0.1:{s.server_port}/",b"secret",{"PROJECT_COMPLETED"})
    await d.publish("PROJECT_COMPLETED",{"id":"p1"}); await d.flush(); s.shutdown()
    body,sig=Handler.requests[-1]; assert hmac.compare_digest(sig,hmac.new(b"secret",body,hashlib.sha256).hexdigest())
    assert json.loads(body)["event"]=="PROJECT_COMPLETED"

@pytest.mark.asyncio
async def test_retries_500_and_records_dead_letter():
    Handler.responses=[500,500,500]; Handler.requests=[]; s=server(); d=WebhookDispatcher(max_retries=2,timeout=1,base_delay=0)
    d.register("a",f"http://127.0.0.1:{s.server_port}/",b"s",{"TASK_FAILED_DLQ"})
    await d.publish("TASK_FAILED_DLQ",{}); await d.flush(); s.shutdown(); assert len(Handler.requests)==3; assert d.dead_letters()[0].attempts==3

@pytest.mark.asyncio
async def test_webhook_failure_is_isolated():
    d=WebhookDispatcher(max_retries=1,timeout=.01,base_delay=0); d.register("bad","http://127.0.0.1:1/",b"s",{"CIRCUIT_BREAKER_OPEN"})
    await d.publish("CIRCUIT_BREAKER_OPEN",{"x":1}); assert True
    await d.flush(); assert len(d.dead_letters())==1

@pytest.mark.asyncio
async def test_event_subscription_filters():
    Handler.responses=[]; Handler.requests=[]; s=server(); d=WebhookDispatcher(timeout=1)
    d.register("a",f"http://127.0.0.1:{s.server_port}/",b"s",{"PROJECT_COMPLETED"})
    await d.publish("TASK_FAILED_DLQ",{}); await d.flush(); s.shutdown(); assert not Handler.requests
