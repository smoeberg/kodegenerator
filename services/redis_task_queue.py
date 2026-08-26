"""Distributed task queue adapter backed by Redis with a memory fallback.

The adapter preserves the core queue semantics of :class:`SwarmTaskQueue`:
atomic worker claiming, ownership-checked lifecycle transitions, capability
matching, dependency gating, leases, and orphan recovery. Redis Lua scripts
keep state transitions atomic across queue consumers on different nodes.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
import json
from threading import RLock
from typing import Any, Optional, Protocol
import uuid


class RedisLike(Protocol):
    """Protocol for the subset of redis-py used by this adapter."""

    def eval(self, script: str, numkeys: int, *args: Any) -> Any: ...


@dataclass
class RedisQueuedTask:
    """Serializable task state stored by the queue."""

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


class RedisTaskQueue:
    """Horizontally scalable queue with an in-memory development fallback.

    Redis is optional at construction time. When supplied, all mutating
    lifecycle operations use Lua scripts so a claim or ownership transition is
    atomic on a shared Redis server. Lease deadlines are indexed in a sorted
    set and can be recovered explicitly with :meth:`recover_orphans`.
    """

    _CLAIM_SCRIPT = """
    local now = tonumber(ARGV[1])
    local lease = tonumber(ARGV[2])
    local agent = ARGV[3]
    local capabilities = cjson.decode(ARGV[4])
    local ids = redis.call('ZRANGE', KEYS[1], 0, -1, 'WITHSCORES')
    local caps = {}
    for _, c in ipairs(capabilities) do caps[c] = true end
    for i = 1, #ids, 2 do
      local id = ids[i]
      local raw = redis.call('HGET', KEYS[2], id)
      if raw then
        local t = cjson.decode(raw)
        if t.status == 'PENDING' then
          local ready = true
          for _, dep in ipairs(t.dependencies or {}) do
            local d = redis.call('HGET', KEYS[2], dep)
            if not d or cjson.decode(d).status ~= 'COMPLETED' then ready = false; break end
          end
          if ready then
            for _, required in ipairs(t.capabilities or {}) do
              if not caps[required] then ready = false; break end
            end
          end
          if ready then
            t.status='CLAIMED'; t.agent_id=agent; t.heartbeat_at=now; t.lease_expires_at=lease
            redis.call('HSET', KEYS[2], id, cjson.encode(t))
            redis.call('ZREM', KEYS[1], id)
            redis.call('ZADD', KEYS[3], lease, id)
            return cjson.encode(t)
          end
        end
      end
    end
    return nil
    """

    _HEARTBEAT_SCRIPT = """
    local raw=redis.call('HGET',KEYS[1],ARGV[1]); if not raw then return 0 end
    local t=cjson.decode(raw); local now=tonumber(ARGV[3]);
    if t.status~='CLAIMED' or t.agent_id~=ARGV[2] or tonumber(t.lease_expires_at or 0)<=now then return 0 end
    t.heartbeat_at=now; t.lease_expires_at=tonumber(ARGV[4]); redis.call('HSET',KEYS[1],ARGV[1],cjson.encode(t)); redis.call('ZADD',KEYS[2],ARGV[4],ARGV[1]); return 1
    """

    _COMPLETE_SCRIPT = """
    local raw=redis.call('HGET',KEYS[1],ARGV[1]); if not raw then return 0 end
    local t=cjson.decode(raw); local now=tonumber(ARGV[3]);
    if t.status=='COMPLETED' then return 1 end
    if t.status~='CLAIMED' or t.agent_id~=ARGV[2] or tonumber(t.lease_expires_at or 0)<=now then return 0 end
    t.status='COMPLETED'; t.patch_result=cjson.decode(ARGV[4]); t.agent_id=cjson.null; t.lease_expires_at=cjson.null; t.heartbeat_at=now
    redis.call('HSET',KEYS[1],ARGV[1],cjson.encode(t)); redis.call('ZREM',KEYS[2],ARGV[1]); return 1
    """

    def __init__(self, redis_client: Optional[RedisLike] = None, *, namespace: str = "dor:swarm", lease_seconds: int = 300) -> None:
        """Initialize the queue."""
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        self.redis = redis_client
        self.namespace = namespace
        self.lease_seconds = lease_seconds
        self._lock = RLock()
        self._tasks: dict[str, RedisQueuedTask] = {}

    def _key(self, suffix: str) -> str:
        """Return a namespaced Redis key."""
        return f"{self.namespace}:{suffix}"

    def enqueue(self, task: Any) -> str:
        """Enqueue a task idempotently and return its task identifier."""
        task_id = self._value(task, "id", "task_id") or str(uuid.uuid4())
        item = self._normalise(task, str(task_id))
        if self.redis is not None:
            # HSETNX is not sufficient for both hash and ready-set atomically;
            # a small transaction script establishes both records together.
            script = """
            if redis.call('HEXISTS',KEYS[1],ARGV[1])==1 then return 0 end
            redis.call('HSET',KEYS[1],ARGV[1],ARGV[2]); redis.call('ZADD',KEYS[2],ARGV[3],ARGV[1]); return 1
            """
            self.redis.eval(script, 2, self._key("tasks"), self._key("ready"), str(task_id), self._encode(item), str(-item.priority))
            return str(task_id)
        with self._lock:
            self._tasks.setdefault(str(task_id), item)
        return str(task_id)

    def claim(self, agent_id: str, capabilities: Optional[list[str]] = None) -> Optional[RedisQueuedTask]:
        """Atomically claim the highest-priority compatible ready task."""
        if not agent_id.strip():
            raise ValueError("agent_id is required")
        now = self._now()
        lease = now + timedelta(seconds=self.lease_seconds)
        caps = capabilities or []
        if self.redis is not None:
            raw = self.redis.eval(self._CLAIM_SCRIPT, 3, self._key("ready"), self._key("tasks"), self._key("leases"), str(now.timestamp()), str(lease.timestamp()), agent_id, json.dumps(caps))
            return None if not raw else self._decode(str(raw))
        with self._lock:
            self._recover_locked(now)
            candidates = [t for t in self._tasks.values() if t.status == "PENDING" and set(t.capabilities).issubset(set(caps)) and self._deps_done(t)]
            if not candidates:
                return None
            task = sorted(candidates, key=lambda t: (-t.priority, t.task_id))[0]
            task.status, task.agent_id = "CLAIMED", agent_id
            task.heartbeat_at, task.lease_expires_at = now, lease
            return task

    def heartbeat(self, task_id: str, agent_id: str) -> None:
        """Extend a live lease owned by ``agent_id``."""
        now = self._now(); lease = now + timedelta(seconds=self.lease_seconds)
        if self.redis is not None:
            ok = self.redis.eval(self._HEARTBEAT_SCRIPT, 2, self._key("tasks"), self._key("leases"), task_id, agent_id, str(now.timestamp()), str(lease.timestamp()))
            if not ok: raise PermissionError("task is not owned by this agent or lease expired")
            return
        with self._lock:
            self._recover_locked(now); task = self._owned(task_id, agent_id)
            task.heartbeat_at, task.lease_expires_at = now, lease

    def complete_task(self, task_id: str, agent_id: str, patch_result: Any) -> None:
        """Complete a live task owned by ``agent_id``."""
        now = self._now()
        if self.redis is not None:
            ok = self.redis.eval(self._COMPLETE_SCRIPT, 2, self._key("tasks"), self._key("leases"), task_id, agent_id, str(now.timestamp()), json.dumps(patch_result))
            if not ok: raise PermissionError("task is not owned by this agent or lease expired")
            return
        with self._lock:
            self._recover_locked(now); task = self._owned(task_id, agent_id)
            task.status, task.patch_result, task.agent_id = "COMPLETED", patch_result, None
            task.lease_expires_at, task.heartbeat_at = None, now

    def fail_task(self, task_id: str, agent_id: str, error: str, retry: bool = True) -> None:
        """Fail a task and optionally return it to the pending set."""
        with self._lock:
            self._recover_locked(self._now()); task = self._owned(task_id, agent_id)
            task.error = error; task.retry_count += 1
            task.status = "PENDING" if retry and task.retry_count <= task.max_retries else "FAILED"
            task.agent_id, task.lease_expires_at = None, None

    def recover_orphans(self) -> int:
        """Release expired Redis leases and return the number recovered."""
        now = self._now()
        if self.redis is not None:
            script = """
            local ids=redis.call('ZRANGEBYSCORE',KEYS[1],'-inf',ARGV[1]); local n=0
            for _,id in ipairs(ids) do local raw=redis.call('HGET',KEYS[2],id); if raw then local t=cjson.decode(raw); if t.status=='CLAIMED' then t.status='PENDING'; t.agent_id=cjson.null; t.lease_expires_at=cjson.null; redis.call('HSET',KEYS[2],id,cjson.encode(t)); redis.call('ZADD',KEYS[3],0,id); n=n+1 end end; redis.call('ZREM',KEYS[1],id) end; return n
            """
            return int(self.redis.eval(script, 3, self._key("leases"), self._key("tasks"), self._key("ready"), str(now.timestamp())))
        with self._lock:
            return self._recover_locked(now)

    def _recover_locked(self, now: datetime) -> int:
        """Recover expired in-memory leases."""
        count = 0
        for task in self._tasks.values():
            if task.status == "CLAIMED" and task.lease_expires_at and task.lease_expires_at <= now:
                task.status, task.agent_id, task.lease_expires_at = "PENDING", None, None; count += 1
        return count

    def _deps_done(self, task: RedisQueuedTask) -> bool:
        """Return whether all local dependencies are completed."""
        return all(self._tasks.get(dep) is not None and self._tasks[dep].status == "COMPLETED" for dep in task.dependencies)

    def _owned(self, task_id: str, agent_id: str) -> RedisQueuedTask:
        """Return an owned live task or raise a permission error."""
        task = self._tasks.get(task_id)
        if task is None: raise KeyError(task_id)
        if task.status != "CLAIMED" or task.agent_id != agent_id: raise PermissionError("task is not claimed by this agent")
        return task

    @staticmethod
    def _value(item: Any, *names: str) -> Any:
        """Read a value from a mapping or object."""
        for name in names:
            if isinstance(item, dict) and name in item: return item[name]
            value = getattr(item, name, None)
            if value is not None: return value
        return None

    @classmethod
    def _normalise(cls, item: Any, task_id: str) -> RedisQueuedTask:
        """Normalise common WBS/queue task objects."""
        deps = tuple(str(x) for x in (cls._value(item, "dependencies") or ()))
        caps = tuple(str(getattr(x, "value", x)) for x in (cls._value(item, "capabilities") or ()))
        metadata = dict(cls._value(item, "metadata") or {})
        if not caps: caps = tuple(str(x) for x in metadata.get("capabilities", ()))
        return RedisQueuedTask(task_id, str(cls._value(item, "name") or task_id), deps, caps, int(cls._value(item, "priority") or 0), metadata=metadata, max_retries=int(cls._value(item, "max_retries") or 3))

    @staticmethod
    def _encode(task: RedisQueuedTask) -> str:
        """Encode a task to JSON."""
        data = asdict(task)
        for key in ("lease_expires_at", "heartbeat_at"):
            data[key] = data[key].timestamp() if data[key] else None
        return json.dumps(data)

    @staticmethod
    def _decode(raw: str) -> RedisQueuedTask:
        """Decode a JSON task representation."""
        data = json.loads(raw)
        for key in ("lease_expires_at", "heartbeat_at"):
            data[key] = datetime.fromtimestamp(data[key], timezone.utc) if data.get(key) else None
        data["dependencies"] = tuple(data.get("dependencies", ())); data["capabilities"] = tuple(data.get("capabilities", ()))
        return RedisQueuedTask(**data)

    @staticmethod
    def _now() -> datetime:
        """Return the current timezone-aware UTC timestamp."""
        return datetime.now(timezone.utc)
