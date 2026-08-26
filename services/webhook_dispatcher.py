"""Asynchronous webhook delivery for critical swarm events."""
from __future__ import annotations
import asyncio, hashlib, hmac, json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
CRITICAL_EVENTS=frozenset(("PROJECT_COMPLETED","TASK_FAILED_DLQ","SECURITY_VIOLATION_BLOCKED","CIRCUIT_BREAKER_OPEN"))
@dataclass(frozen=True)
class WebhookEndpoint: endpoint_id:str; url:str; secret:bytes; events:frozenset[str]
@dataclass(frozen=True)
class DeadLetter: endpoint_id:str; event_type:str; payload:dict[str,Any]; attempts:int; last_error:str; failed_at:str
class WebhookDispatcher:
 def __init__(self,*,max_retries:int=3,timeout:float=5.0,base_delay:float=.1):
  if max_retries<0 or timeout<=0 or base_delay<0: raise ValueError("invalid retry/timeout configuration")
  self.max_retries=max_retries; self.timeout=timeout; self.base_delay=base_delay; self._endpoints={}; self._dead_letters=[]; self._tasks=set()
 def register(self,endpoint_id,url,secret,events=None):
  if not endpoint_id or not url: raise ValueError("endpoint_id and url are required")
  ev=frozenset(events or CRITICAL_EVENTS); bad=ev-CRITICAL_EVENTS
  if bad: raise ValueError(f"unsupported event types: {sorted(bad)}")
  x=WebhookEndpoint(endpoint_id,url,secret.encode() if isinstance(secret,str) else bytes(secret),ev); self._endpoints[endpoint_id]=x; return x
 def unregister(self,endpoint_id): self._endpoints.pop(endpoint_id,None)
 def dead_letters(self): return tuple(self._dead_letters)
 async def publish(self,event_type,payload:Mapping[str,Any]):
  if event_type not in CRITICAL_EVENTS: raise ValueError(f"unsupported event type: {event_type}")
  for ep in tuple(self._endpoints.values()):
   if event_type in ep.events:
    t=asyncio.create_task(self._deliver(ep,event_type,dict(payload))); self._tasks.add(t); t.add_done_callback(self._tasks.discard)
  await asyncio.sleep(0)
 async def flush(self):
  if self._tasks: await asyncio.gather(*tuple(self._tasks),return_exceptions=True)
 async def _deliver(self,ep,event_type,payload):
  env={"event":event_type,"timestamp":datetime.now(timezone.utc).isoformat(),"payload":payload}; body=json.dumps(env,sort_keys=True,separators=(",",":"),ensure_ascii=False).encode(); sig=hmac.new(ep.secret,body,hashlib.sha256).hexdigest(); err=""; attempts=0
  for attempt in range(self.max_retries+1):
   attempts=attempt+1
   try:
    status=await asyncio.to_thread(self._post,ep.url,body,sig)
    if 200<=status<300:return
    err=f"HTTP {status}"
   except Exception as exc: err=f"{type(exc).__name__}: {exc}"
   if attempt<self.max_retries: await asyncio.sleep(self.base_delay*2**attempt)
  self._dead_letters.append(DeadLetter(ep.endpoint_id,event_type,payload,attempts,err,datetime.now(timezone.utc).isoformat()))
 def _post(self,url,body,signature):
  req=Request(url,data=body,method="POST",headers={"Content-Type":"application/json","X-Swarm-Signature":signature})
  try:
   with urlopen(req,timeout=self.timeout) as response:return int(response.status)
  except HTTPError as exc:return int(exc.code)
  except URLError as exc:raise TimeoutError(str(exc)) from exc
