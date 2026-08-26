import json
import threading
from services.performance_profiler import PerformanceProfiler

def test_percentiles_known_dataset():
    p=PerformanceProfiler()
    for i in range(1,101): p.record_stage("t", "CLAIM", i)
    s=p.stage_stats("CLAIM")
    assert s.samples==100
    assert s.p50==50.5
    assert s.p95==95.05
    assert s.p99==99.01

def test_bottleneck_detection():
    p=PerformanceProfiler()
    for x in [10,20,30,40,100]: p.record_stage(str(x),"SYNTHESIZE",x)
    for x in [1,2,3,4,5]: p.record_stage(str(x),"CLAIM",x)
    b=p.bottlenecks(50)
    assert len(b)==1 and b[0].stage=="SYNTHESIZE"

def test_task_report_chronology_and_total():
    p=PerformanceProfiler()
    p.record_stage("task-1","ENQUEUE",10)
    p.record_stage("task-1","CLAIM",20)
    p.record_stage("task-1","COMPLETE",30)
    r=p.task_report("task-1")
    assert [x.stage for x in r.stages]==["ENQUEUE","CLAIM","COMPLETE"]
    assert r.total_duration_ms==60

def test_thread_safety_keeps_all_samples():
    p=PerformanceProfiler()
    def add(offset):
        for i in range(100): p.record_stage(f"t-{offset}-{i}","ENQUEUE",i)
    threads=[threading.Thread(target=add,args=(i,)) for i in range(20)]
    for t in threads:t.start()
    for t in threads:t.join()
    assert p.stage_stats("ENQUEUE").samples==2000
    assert len(json.loads(p.dump_json()))==2000
