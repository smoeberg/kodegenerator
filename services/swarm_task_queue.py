"""Swarm task queue used by the HTTP control plane."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from threading import RLock
from typing import Any, Optional
import uuid

@dataclass
class QueuedTask:
    task_id: str
    name: str
    dependencies: tuple[str, ...] = ()
    capabilities: tuple[str, ...] = ()
    priority: int = 0
    status: str = "PENDING"
    agent_id: Optional[str] = None
    lease_expires_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    retry_count: int = 0
    max_retries: int = 3
    error: Optional[str] = None
    patch_result: Any = None
    metadata: dict[str, Any] = field(default_factory=dict)

class SwarmTaskQueue:
    def __init__(self, *, lease_seconds: int = 300) -> None:
        if lease_seconds <= 0: raise ValueError("lease_seconds must be positive")
        self.lease_seconds=lease_seconds; self._lock=RLock(); self._tasks={}; self._plans=set()
    @staticmethod
    def _now(): return datetime.now(timezone.utc)
    @staticmethod
    def _v(x,*names):
        for n in names:
            if isinstance(x,dict) and n in x: return x[n]
            v=getattr(x,n,None)
            if v is not None:return v
        return None
    def enqueue_wbs_plan(self,plan):
        pid=str(self._v(plan,"plan_id","wbs_id","id") or uuid.uuid4()); raw=self._v(plan,"tasks","wbs_tasks")
        if raw is None and isinstance(plan,(list,tuple)):raw=plan
        if raw is None:raise TypeError("WBS plan must expose tasks or wbs_tasks")
        with self._lock:
            if pid in self._plans:return 0
            count=0
            for x in raw:
                tid=str(self._v(x,"task_id","id") or uuid.uuid4()); md=dict(self._v(x,"metadata") or {}); caps=self._v(x,"capabilities") or md.get("capabilities",[]); caps=tuple(getattr(c,"value",str(c)) for c in caps); deps=tuple(str(d) for d in(self._v(x,"dependencies") or [])); p=self._v(x,"priority") or 0; p=int(getattr(p,"value",p))
                if tid in self._tasks:continue
                self._tasks[tid]=QueuedTask(tid,str(self._v(x,"name") or tid),deps,caps,p,metadata=md,max_retries=int(self._v(x,"max_retries") or 3));count+=1
            self._plans.add(pid);return count
    def _reclaim(self,now):
        for t in self._tasks.values():
            if t.status=="CLAIMED" and t.lease_expires_at and t.lease_expires_at<=now:t.status="PENDING";t.agent_id=None;t.lease_expires_at=None
    def claim_next_task(self,agent_id,capabilities):
        if not agent_id.strip():raise ValueError("agent_id is required")
        with self._lock:
            now=self._now();self._reclaim(now);caps=set(capabilities); ready=[t for t in self._tasks.values() if t.status=="PENDING" and set(t.capabilities).issubset(caps) and all(self._tasks.get(d) and self._tasks[d].status=="COMPLETED" for d in t.dependencies)]
            if not ready:return None
            t=sorted(ready,key=lambda x:(-x.priority,x.task_id))[0];t.status="CLAIMED";t.agent_id=agent_id;t.heartbeat_at=now;t.lease_expires_at=now+timedelta(seconds=self.lease_seconds);return t
    def _owned(self,tid,agent):
        t=self._tasks.get(tid)
        if t is None:raise KeyError(tid)
        if t.status!="CLAIMED" or t.agent_id!=agent:raise PermissionError("task is not claimed by this worker")
        if not t.lease_expires_at or t.lease_expires_at<=self._now():self._reclaim(self._now());raise RuntimeError("task lease has expired")
        return t
    def heartbeat(self,tid,agent):
        with self._lock:
            t=self._owned(tid,agent);now=self._now();t.heartbeat_at=now;t.lease_expires_at=now+timedelta(seconds=self.lease_seconds);return t
    def complete_task(self,tid,agent,result):
        with self._lock:
            t=self._owned(tid,agent);t.status="COMPLETED";t.patch_result=result;t.agent_id=None;t.lease_expires_at=None;return t
    def fail_task(self,tid,agent,error,retry=True):
        with self._lock:
            t=self._owned(tid,agent);t.error=error;t.retry_count+=1;t.status="PENDING" if retry and t.retry_count<=t.max_retries else "FAILED";t.agent_id=None;t.lease_expires_at=None;return t
    def get_task(self,tid):
        with self._lock:
            self._reclaim(self._now())
            if tid not in self._tasks:raise KeyError(tid)
            return self._tasks[tid]
    def tasks_for_project(self,pid):
        with self._lock:
            self._reclaim(self._now());return [t for t in self._tasks.values() if t.metadata.get("project_id")==pid]
