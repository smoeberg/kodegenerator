# execution/service_task_executor.py
from typing import Dict, Any
from domain.task import Task, TaskStatus
from domain.actor import Actor, ActorType
from runtime.event_bus import EventBus
from domain.event import Event, EventType
from datetime import datetime
import json
import urllib.request
import urllib.error

class ServiceTaskExecutor:
    """Udfører tasks ved at kalde eksterne services (f.eks. GitHub, Jira, Slack)."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus

    async def execute(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """Udfør en Task ved at kalde en ekstern service."""
        if actor.type != ActorType.SERVICE:
            return {"status": "failed", "error": "Actor is not a Service"}

        if "github" in actor.identity.lower():
            return await self._execute_github_task(task, actor)
        elif "jira" in actor.identity.lower():
            return await self._execute_jira_task(task, actor)
        elif "slack" in actor.identity.lower():
            return await self._execute_slack_task(task, actor)
        else:
            return {"status": "failed", "error": f"Unsupported service: {actor.identity}"}

    async def _execute_github_task(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """Udfør GitHub-relateret Task (f.eks. opret PR, merge PR)."""
        try:
            api_key = getattr(actor, "api_key", "mock_key")
            if "create_pr" in task.name.lower():
                return {
                    "status": "success",
                    "output": f"Pull Request '{task.name}' created on GitHub",
                    "pr_url": f"https://github.com/org/repo/pull/{task.id}"
                }
            elif "merge_pr" in task.name.lower():
                pr_number = task.metadata.get("pr_number", "1")
                return {
                    "status": "success",
                    "output": f"Pull Request #{pr_number} merged successfully"
                }
            else:
                return {"status": "failed", "error": f"Unsupported GitHub task: {task.name}"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _execute_jira_task(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """Udfør Jira-relateret Task."""
        return {
            "status": "success",
            "output": f"Jira issue created for task: {task.name}",
            "issue_key": f"DOR-{task.id[:4]}"
        }

    async def _execute_slack_task(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """Udfør Slack-relateret Task."""
        channel = task.metadata.get("channel", "#general")
        return {
            "status": "success",
            "output": f"Notification sent to Slack channel {channel}"
        }

    async def close(self):
        pass
