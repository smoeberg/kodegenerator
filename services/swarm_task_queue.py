"""Storage-agnostic facade for the swarm task queue."""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from threading import RLock
from typing import Any, Optional
import uuid

class QueuedTaskStatus(str, Enum):
    PENDING="PENDING"; CLAIMED="CLAIMED"; COMPLETED="COMPLETED"; FAILED="FAILED"
@dataclass
class QueuedTask:
    task_id:str; name:str; dependencies:tuple[str,...]=(); capabilities:tuple[str,...]=(); priority:int=0; status:QueuedTaskStatus=QueuedTaskStatus.PENDING; agent_id:Optional[str]=None; lease_expires_at:Optional[datetime]=None; heartbeat_at:Optional[datetime]=None; retry_count:int=0; max_retries:int=3; error:Optional[str]=None; patch_result:Any=None; metadata:dict[str,Any]=field(default_factory=dict)
    def lease_active(self,now): return self.status==QueuedTaskStatus.CLAIMED and bool(self.lease_expires_at and self.lease_expires_at>now)

class _MemoryTaskQueue:
    def __init__(self,*,lease_seconds=300,clock=None):
        if lease_seconds<=0: raise ValueError("lease_seconds must be positive")
        self.lease_seconds=lease_seconds; self._clock=clock or (lambda:datetime.now(timezone.utc)); self._lock=RLock(); self._tasks={}; self._plan_keys=set()
    def enqueue_wbs_plan(self,plan):
        key=self._plan_key(plan); tasks=self._extract_tasks(plan)
        with self._lock:
            if key in self._plan_keys:return 0
            n=0
            for x in tasks:
                t=self._normalise_task(x)
                if t.task_id not in self._tasks:self._tasks[t.task_id]=t;n+=1
            self._plan_keys.add(key);return n
    def submit_task(self,task,**_):
        t=task if isinstance(task,QueuedTask) else self._normalise_task(task); self._tasks.setdefault(t.task_id,t); return t.task_id
    def claim_next_task(self,agent_id,capabilities):
        if not agent_id.strip():raise ValueError("agent_id is required")
        with self._lock:
            now=self._clock();self._reclaim(now);ready=[t for t in self._tasks.values() if t.status==QueuedTaskStatus.PENDING and set(t.capabilities).issubset(capabilities) and self._deps(t)]
            if not ready:return None
            t=sorted(ready,key=lambda x:(-x.priority,x.task_id))[0];t.status=QueuedTaskStatus.CLAIMED;t.agent_id=agent_id;t.heartbeat_at=now;t.lease_expires_at=now+timedelta(seconds=self.lease_seconds);return t
    def heartbeat(self,tid,agent):
        t=self._owned(tid,agent)
        now=self._clock()
        if not t.lease_active(now):self._reclaim(now);raise RuntimeError("task lease has expired")
        t.heartbeat_at=now;t.lease_expires_at=now+timedelta(seconds=self.lease_seconds)
    def complete_task(self,tid,agent,result):
        t=self._owned(tid,agent);now=self._clock()
        if not t.lease_active(now):self._reclaim(now);raise RuntimeError("task lease has expired")
        t.status=QueuedTaskStatus.COMPLETED;t.patch_result=result;t.agent_id=None;t.lease_expires_at=None;t.heartbeat_at=now
    def fail_task(self,tid,agent,error,retry=True):
        t=self._owned(tid,agent);t.error=error;t.retry_count+=1;t.status=QueuedTaskStatus.PENDING if retry and t.retry_count<=t.max_retries else QueuedTaskStatus.FAILED;t.agent_id=None;t.lease_expires_at=None;t.heartbeat_at=self._clock()
    def reclaim_expired(self):
        with self._lock:return self._reclaim(self._clock())
    def get_queue_stats(self):
        self.reclaim_expired();return {s.value.lower():sum(t.status==s for t in self._tasks.values()) for s in QueuedTaskStatus}
    def pending_count(self):return self.get_queue_stats().get("pending",0)
    def get_task(self,tid):return self._tasks[tid]
    def _reclaim(self,now):
        n=0
        for t in self._tasks.values():
            if t.status==QueuedTaskStatus.CLAIMED and not t.lease_active(now):t.status=QueuedTaskStatus.PENDING;t.agent_id=None;t.lease_expires_at=None;n+=1
        return n
    def _owned(self,tid,agent):
        t=self._tasks.get(tid)
        if not t:raise KeyError(tid)
        if t.status!=QueuedTaskStatus.CLAIMED or t.agent_id!=agent:raise PermissionError("task is not claimed by this agent")
        return t
    def _deps(self,t):return all(self._tasks.get(d) and self._tasks[d].status==QueuedTaskStatus.COMPLETED for d in t.dependencies)
    @staticmethod
    def _extract_tasks(plan):return list(getattr(plan,"tasks",getattr(plan,"wbs_tasks",plan)))
    @staticmethod
    def _plan_key(plan):return "plan:"+str(getattr(plan,"plan_id",getattr(plan,"id",id(plan))))
    @staticmethod
    def _normalise_task(x):
        tid=str(getattr(x,"task_id",getattr(x,"id",None)) or uuid.uuid4());caps=tuple(getattr(c,"value",str(c)) for c in (getattr(x,"capabilities",[]) or []));return QueuedTask(tid,str(getattr(x,"name",tid)),tuple(map(str,getattr(x,"dependencies",[]) or [])),caps,int(getattr(x,"priority",0) or 0),max_retries=int(getattr(x,"max_retries",3)),metadata=dict(getattr(x,"metadata",{}) or {}))

class SwarmTaskQueue:
    """Facade selecting in-memory (default) or SQLite persistence."""
    def __init__(self, *, lease_seconds=300, clock=None, backend="memory", db_path="swarm.db"):
        if backend in ("sqlite","durable"):
            from .swarm_persistence import SQLiteTaskQueue
            self._backend=SQLiteTaskQueue(db_path,lease_seconds=lease_seconds,clock=clock)
        else:self._backend=_MemoryTaskQueue(lease_seconds=lease_seconds,clock=clock)
    def __getattr__(self,name):return getattr(self._backend,name)
