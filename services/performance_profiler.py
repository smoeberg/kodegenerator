"""Thread-safe pipeline stage performance profiler."""
from __future__ import annotations
import json
import threading
from dataclasses import asdict, dataclass
from statistics import mean
STAGES=("ENQUEUE","CLAIM","SYNTHESIZE","SENTINEL_VERIFY","COMPLETE","RETRY_BACKOFF")
@dataclass(frozen=True)
class StageSample: task_id:str; stage:str; duration_ms:float; sequence:int
@dataclass(frozen=True)
class Stats: p50:float; p95:float; p99:float; average:float; max:float; samples:int
@dataclass(frozen=True)
class Bottleneck: stage:str; stats:Stats
@dataclass(frozen=True)
class Timeline: task_id:str; stages:tuple[StageSample,...]; total_duration_ms:float
class PerformanceProfiler:
 def __init__(self): self._lock=threading.RLock(); self._history=[]; self._sequence=0
 def record_stage(self,task_id,stage,duration_ms):
  stage=stage.upper()
  if stage not in STAGES: raise ValueError(f"unknown stage: {stage}")
  if duration_ms<0: raise ValueError("duration_ms must be non-negative")
  with self._lock:
   self._sequence+=1; self._history.append(StageSample(str(task_id),stage,float(duration_ms),self._sequence))
 @staticmethod
 def _p(v,q):
  if not v:return 0.0
  v=sorted(v);r=(len(v)-1)*q/100;lo=int(r);hi=min(lo+1,len(v)-1);return v[lo]+(v[hi]-v[lo])*(r-lo)
 def stage_stats(self,stage):
  with self._lock:v=[x.duration_ms for x in self._history if x.stage==stage.upper()]
  return Stats(self._p(v,50),self._p(v,95),self._p(v,99),mean(v) if v else 0,max(v) if v else 0,len(v))
 def bottlenecks(self,threshold_p95_ms):
  r=[]
  for s in STAGES:
   x=self.stage_stats(s)
   if x.samples and x.p95>threshold_p95_ms:r.append(Bottleneck(s,x))
  return sorted(r,key=lambda x:x.stats.p95,reverse=True)
 def task_report(self,task_id):
  with self._lock:s=tuple(sorted((x for x in self._history if x.task_id==str(task_id)),key=lambda x:x.sequence))
  return Timeline(str(task_id),s,sum(x.duration_ms for x in s))
 def dump_json(self):
  with self._lock:return json.dumps([asdict(x) for x in self._history],sort_keys=True)
 dumps=dump_json
 def history(self):
  with self._lock:return tuple(self._history)
