# execution/service_task_executor.py
from typing import Dict, Any
from domain.task import Task, TaskStatus
from domain.actor import Actor, ActorType
from runtime.event_bus import EventBus
from domain.event import Event, EventType
from datetime import datetime
import httpx

class ServiceTaskExecutor:
    """Udfører tasks ved at kalde eksterne services (f.eks. GitHub, Jira)."""

    def __init__(self, event_bus: EventBus):
        self.event_bus = event_bus
        self.http_client = httpx.AsyncClient()

    async def execute(self, task: Task, actor: Actor) -> Dict[str, Any]:
        """
        Udfør en Task ved at kalde en ekstern service.
        """
        if actor.type != ActorType.SERVICE:
            return {"status": "failed", "error": "Actor is not a Service"}

        # Bestem handling baseret på Actor-navn
        if "github" in actor.identity.lower():
            return await self._execute_github_task(task, actor)
        elif "jira" in actor.identity.lower():
            return await self._execute_jira_task(task, actor)
        elif "slack" in actor.identity.lower():
            return await self._execute_slack_task(task, actor)
        else:
            return {"status": "failed", "error": f"Unsupported service: {actor.identity}"}

    async def _execute_github_task(
        self,
        task: Task,
        actor: Actor
    ) -> Dict[str, Any]:
        """Udfør en GitHub-relateret Task (f.eks. opret PR, merge, etc.)."""
        # Simuler GitHub API-kald
        # I praksis ville vi bruge actor.api_key og actor.api_url
        try:
            # Eksempel: Opret en Pull Request
            if "create_pr" in task.name.lower():
                response = await self.http_client.post(
                    "https://api.github.com/repos/owner/repo/pulls",
                    json={
                        "title": task.name,
                        "body": task.description,
                        "head": "feature-branch",
                        "base": "main"
                    },
                    headers={
                        "Authorization": f"Bearer {actor.api_key}",
                        "Accept": "application/vnd.github+json"
                    }
                )
                response.raise_for_status()
                return {
                    "status": "success",
                    "output": f"Pull Request created: {response.json()['html_url']}"
                }
            # Eksempel: Merge en Pull Request
            elif "merge_pr" in task.name.lower():
                pr_number = task.metadata.get("pr_number")
                if not pr_number:
                    return {"status": "failed", "error": "PR number not specified"}
                response = await self.http_client.put(
                    f"https://api.github.com/repos/owner/repo/pulls/{pr_number}/merge",
                    headers={
                        "Authorization": f"Bearer {actor.api_key}",
                        "Accept": "application/vnd.github+json"
                    }
                )
                response.raise_for_status()
                return {
                    "status": "success",
                    "output": f"Pull Request {pr_number} merged"
                }
            else:
                return {"status": "failed", "error": f"Unsupported GitHub task: {task.name}"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _execute_jira_task(
        self,
        task: Task,
        actor: Actor
    ) -> Dict[str, Any]:
        """Udfør en Jira-relateret Task (f.eks. opret issue, opdater status)."""
        try:
            # Eksempel: Opret et Jira Issue
            if "create_issue" in task.name.lower():
                response = await self.http_client.post(
                    "https://your-domain.atlassian.net/rest/api/2/issue",
                    json={
                        "fields": {
                            "project": {"key": "PROJ"},
                            "summary": task.name,
                            "description": task.description,
                            "issuetype": {"name": "Task"}
                        }
                    },
                    headers={
                        "Authorization": f"Bearer {actor.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                return {
                    "status": "success",
                    "output": f"Jira Issue created: {response.json()['key']}"
                }
            else:
                return {"status": "failed", "error": f"Unsupported Jira task: {task.name}"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def _execute_slack_task(
        self,
        task: Task,
        actor: Actor
    ) -> Dict[str, Any]:
        """Udfør en Slack-relateret Task (f.eks. send besked)."""
        try:
            # Eksempel: Send en besked til Slack
            if "send_message" in task.name.lower():
                channel = task.metadata.get("channel", "#general")
                response = await self.http_client.post(
                    "https://slack.com/api/chat.postMessage",
                    json={
                        "channel": channel,
                        "text": task.description
                    },
                    headers={
                        "Authorization": f"Bearer {actor.api_key}",
                        "Content-Type": "application/json"
                    }
                )
                response.raise_for_status()
                if not response.json()["ok"]:
                    return {"status": "failed", "error": response.json()["error"]}
                return {
                    "status": "success",
                    "output": f"Message sent to {channel}"
                }
            else:
                return {"status": "failed", "error": f"Unsupported Slack task: {task.name}"}
        except Exception as e:
            return {"status": "failed", "error": str(e)}

    async def close(self):
        """Luk HTTP-client."""
        await self.http_client.aclose()
