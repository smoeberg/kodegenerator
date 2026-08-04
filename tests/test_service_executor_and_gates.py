
import asyncio
from domain.actor import Actor, ActorType
from domain.task import Task, TaskStatus, TaskPriority
from runtime.event_bus import EventBus
from execution.service_task_executor import ServiceTaskExecutor
from execution.human_task_executor import HumanTaskExecutor


async def test_human_task_executor_notification():
    event_bus = EventBus()
    executor = HumanTaskExecutor(event_bus=event_bus)
    
    actor = Actor(id="human-1", identity="Supervisor John", type=ActorType.HUMAN)
    task = Task(id="t-1", name="Approve Architecture", description="Please review ADR-001", priority=TaskPriority.HIGH)
    
    res = await executor.execute(task, actor)
    assert res["status"] == "pending"
    assert "Notification sent" in res["message"]
    assert len(event_bus.events) == 1

if __name__ == "__main__":
    asyncio.run(test_human_task_executor_notification())
    print("✅ Service & Governance Executor Tests Passed!")
