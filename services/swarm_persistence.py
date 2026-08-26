"""Durable SQLite persistence for the swarm task queue."""
from __future__ import annotations
import json, sqlite3, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Optional
from .swarm_task_queue import QueuedTask, QueuedTaskStatus

def _dt(v): return datetime.fromisoformat(v) if v else None
def _iso(v): return v.isoformat() if v else None

class SQLiteTaskQueue:
    """Crash-safe SQLite queue using WAL and BEGIN IMMEDIATE claims."""
    def __init__(self, db_path: str|Path="swarm.db", *, lease_seconds=300, clock=None):
        if lease_seconds <= 0: raise ValueError("lease_seconds must be positive")
        self.lease_seconds=lease_seconds; self._clock=clock or (lambda: datetime.now(timezone.utc)); self._lock=RLock()
        self._conn=sqlite3.connect(str(db_path), check_same_thread=False, timeout=30); self._conn.row_factory=sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL"); self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript("""
CREATE TABLE IF NOT EXISTS tasks(task_id TEXT PRIMARY KEY,name TEXT NOT NULL,status TEXT NOT NULL,capabilities TEXT NOT NULL,priority INTEGER NOT NULL DEFAULT 0,agent_id TEXT,lease_expires_at TEXT,heartbeat_at TEXT,retry_count INTEGER NOT NULL DEFAULT 0,max_retries INTEGER NOT NULL DEFAULT 3,error TEXT,patch_result TEXT,metadata TEXT NOT NULL DEFAULT '{}');
CREATE TABLE IF NOT EXISTS claims(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT NOT NULL REFERENCES tasks(task_id),agent_id TEXT NOT NULL,claimed_at TEXT NOT NULL,lease_expires_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS dependencies(task_id TEXT NOT NULL REFERENCES tasks(task_id) ON DELETE CASCADE,dependency_id TEXT NOT NULL,PRIMARY KEY(task_id,dependency_id));
CREATE TABLE IF NOT EXISTS audit_events(id INTEGER PRIMARY KEY AUTOINCREMENT,task_id TEXT,event_type TEXT NOT NULL,agent_id TEXT,created_at TEXT NOT NULL,details TEXT NOT NULL DEFAULT '{}');
CREATE INDEX IF NOT EXISTS idx_tasks_ready ON tasks(status,priority DESC,task_id);
"""); self._conn.commit()
    def close(self): self._conn.close()
    def submit_task(self, task: QueuedTask|Any, **kwargs):
        t=task if isinstance(task,QueuedTask) else self._normalise(task,**kwargs)
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._conn.execute("INSERT OR IGNORE INTO tasks(task_id,name,status,capabilities,priority,max_retries,metadata) VALUES(?,?,?,?,?,?,?)",(t.task_id,t.name,t.status.value,json.dumps(t.capabilities),t.priority,t.max_retries,json.dumps(t.metadata)))
                for d in t.dependencies: self._conn.execute("INSERT OR IGNORE INTO dependencies VALUES(?,?)",(t.task_id,d))
                self._audit(t.task_id,"submitted",None,{}); self._conn.commit()
            except: self._conn.rollback(); raise
        return t.task_id
    def enqueue_wbs_plan(self, plan):
        before=self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        for x in getattr(plan,"tasks",getattr(plan,"wbs_tasks",plan)): self.submit_task(x)
        return self._conn.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]-before
    def claim_next_task(self, agent_id, capabilities):
        if not agent_id.strip(): raise ValueError("agent_id is required")
        with self._lock:
            now=self._clock(); exp=now+timedelta(seconds=self.lease_seconds); self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._reclaim(now); rows=self._conn.execute("SELECT * FROM tasks WHERE status='PENDING' ORDER BY priority DESC,task_id").fetchall()
                chosen=next((r for r in rows if set(json.loads(r['capabilities'])).issubset(capabilities) and self._deps_done(r['task_id'])),None)
                if not chosen: self._conn.commit(); return None
                self._conn.execute("UPDATE tasks SET status='CLAIMED',agent_id=?,heartbeat_at=?,lease_expires_at=? WHERE task_id=?",(agent_id,_iso(now),_iso(exp),chosen['task_id']))
                self._conn.execute("INSERT INTO claims(task_id,agent_id,claimed_at,lease_expires_at) VALUES(?,?,?,?)",(chosen['task_id'],agent_id,_iso(now),_iso(exp))); self._audit(chosen['task_id'],"claimed",agent_id,{"lease_expires_at":_iso(exp)}); self._conn.commit(); return self.get_task(chosen['task_id'])
            except: self._conn.rollback(); raise
    def heartbeat(self, task_id, agent_id):
        self._transition(task_id,agent_id,"heartbeat")
    def complete_task(self, task_id, agent_id, patch_result): self._transition(task_id,agent_id,"complete",patch_result)
    def fail_task(self, task_id, agent_id, error, retry=True):
        with self._lock:
            now=self._clock(); self._conn.execute("BEGIN IMMEDIATE")
            try:
                r=self._owned(task_id,agent_id,now); n=r['retry_count']+1; s='PENDING' if retry and n<=r['max_retries'] else 'FAILED'
                self._conn.execute("UPDATE tasks SET status=?,retry_count=?,error=?,agent_id=NULL,lease_expires_at=NULL,heartbeat_at=? WHERE task_id=?",(s,n,error,_iso(now),task_id)); self._audit(task_id,"failed",agent_id,{"error":error}); self._conn.commit()
            except: self._conn.rollback(); raise
    def reclaim_expired(self):
        with self._lock:
            self._conn.execute("BEGIN IMMEDIATE")
            try: n=self._reclaim(self._clock()); self._conn.commit(); return n
            except: self._conn.rollback(); raise
    def get_queue_stats(self):
        self.reclaim_expired(); return {r['status'].lower():r['n'] for r in self._conn.execute("SELECT status,COUNT(*) n FROM tasks GROUP BY status")}
    def pending_count(self): return self.get_queue_stats().get('pending',0)
    def get_task(self, task_id):
        r=self._conn.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone()
        if not r: raise KeyError(task_id)
        deps=tuple(x[0] for x in self._conn.execute("SELECT dependency_id FROM dependencies WHERE task_id=?",(task_id,)))
        return QueuedTask(task_id=r['task_id'],name=r['name'],dependencies=deps,capabilities=tuple(json.loads(r['capabilities'])),priority=r['priority'],status=QueuedTaskStatus(r['status']),agent_id=r['agent_id'],lease_expires_at=_dt(r['lease_expires_at']),heartbeat_at=_dt(r['heartbeat_at']),retry_count=r['retry_count'],max_retries=r['max_retries'],error=r['error'],patch_result=json.loads(r['patch_result']) if r['patch_result'] else None,metadata=json.loads(r['metadata']))
    def _transition(self,tid,agent,kind,result=None):
        with self._lock:
            now=self._clock(); self._conn.execute("BEGIN IMMEDIATE")
            try:
                self._owned(tid,agent,now)
                if kind=="heartbeat": exp=now+timedelta(seconds=self.lease_seconds); self._conn.execute("UPDATE tasks SET heartbeat_at=?,lease_expires_at=? WHERE task_id=?",(_iso(now),_iso(exp),tid)); details={"lease_expires_at":_iso(exp)}
                else: self._conn.execute("UPDATE tasks SET status='COMPLETED',patch_result=?,agent_id=NULL,lease_expires_at=NULL,heartbeat_at=? WHERE task_id=?",(json.dumps(result),_iso(now),tid)); details={}
                self._audit(tid,kind,agent,details); self._conn.commit()
            except: self._conn.rollback(); raise
    def _owned(self,tid,agent,now):
        r=self._conn.execute("SELECT * FROM tasks WHERE task_id=?",(tid,)).fetchone()
        if not r: raise KeyError(tid)
        if r['status']!='CLAIMED' or r['agent_id']!=agent: raise PermissionError("task is not claimed by this agent")
        if _dt(r['lease_expires_at'])<=now: self._reclaim(now); raise RuntimeError("task lease has expired")
        return r
    def _reclaim(self,now):
        rows=self._conn.execute("SELECT task_id,agent_id FROM tasks WHERE status='CLAIMED' AND lease_expires_at<=?",(_iso(now),)).fetchall()
        for r in rows: self._conn.execute("UPDATE tasks SET status='PENDING',agent_id=NULL,lease_expires_at=NULL WHERE task_id=?",(r['task_id'],)); self._audit(r['task_id'],"lease_expired",r['agent_id'],{})
        return len(rows)
    def _deps_done(self,tid):
        return all((r:=self._conn.execute("SELECT status FROM tasks WHERE task_id=?",(d[0],)).fetchone()) and r[0]=='COMPLETED' for d in self._conn.execute("SELECT dependency_id FROM dependencies WHERE task_id=?",(tid,)))
    def _audit(self,tid,event,agent,details): self._conn.execute("INSERT INTO audit_events(task_id,event_type,agent_id,created_at,details) VALUES(?,?,?,?,?)",(tid,event,agent,_iso(self._clock()),json.dumps(details)))
    @staticmethod
    def _normalise(x,task_id=None,**kwargs):
        tid=task_id or str(getattr(x,'task_id',getattr(x,'id',None)) or uuid.uuid4()); caps=tuple(getattr(c,'value',str(c)) for c in (getattr(x,'capabilities',None) or kwargs.get('capabilities',[])))
        return QueuedTask(task_id=tid,name=str(getattr(x,'name',tid)),dependencies=tuple(map(str,getattr(x,'dependencies',[]) or [])),capabilities=caps,priority=int(getattr(x,'priority',0) or 0),max_retries=int(getattr(x,'max_retries',3)),metadata=dict(getattr(x,'metadata',{}) or {}))
