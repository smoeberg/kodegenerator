# monitoring/metrics.py
from prometheus_client import start_http_server, Counter, Gauge, Histogram, Summary
import time

# --- Metrics ---
# Task Metrics
TASKS_SUBMITTED = Counter(
    "dor_tasks_submitted_total",
    "Total number of tasks submitted",
    ["organization_id", "workflow_id", "task_type"]
)

TASKS_COMPLETED = Counter(
    "dor_tasks_completed_total",
    "Total number of tasks completed",
    ["organization_id", "workflow_id", "task_type", "status"]
)

TASK_DURATION = Histogram(
    "dor_task_duration_seconds",
    "Duration of task execution in seconds",
    ["organization_id", "workflow_id", "task_type"]
)

# Workflow Metrics
WORKFLOWS_STARTED = Counter(
    "dor_workflows_started_total",
    "Total number of workflows started",
    ["organization_id", "template_id"]
)

WORKFLOWS_COMPLETED = Counter(
    "dor_workflows_completed_total",
    "Total number of workflows completed",
    ["organization_id", "template_id", "status"]
)

WORKFLOW_DURATION = Histogram(
    "dor_workflow_duration_seconds",
    "Duration of workflow execution in seconds",
    ["organization_id", "template_id"]
)

# AI Metrics
AI_CALLS = Counter(
    "dor_ai_calls_total",
    "Total number of AI calls",
    ["model_id", "provider", "task_type"]
)

AI_CALL_DURATION = Histogram(
    "dor_ai_call_duration_seconds",
    "Duration of AI calls in seconds",
    ["model_id", "provider"]
)

AI_TOKENS_USED = Counter(
    "dor_ai_tokens_used_total",
    "Total number of tokens used",
    ["model_id", "provider", "token_type"]  # token_type: "input" or "output"
)

# System Metrics
ACTIVE_TASKS = Gauge(
    "dor_active_tasks",
    "Number of active tasks",
    ["organization_id"]
)

PENDING_TASKS = Gauge(
    "dor_pending_tasks",
    "Number of pending tasks",
    ["organization_id"]
)

# --- Metrics Server ---
def start_metrics_server(port: int = 8000) -> None:
    """Start Prometheus metrics server."""
    start_http_server(port)
    print(f"Prometheus metrics server started on port {port}")

# --- Metrics Decorators ---
def track_task_metrics(func):
    """Decorator til at tracke Task Metrics."""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time

            # Hent task_id fra kwargs
            task_id = kwargs.get("task_id")
            if task_id:
                task = args[0].db_adapter.get_task(task_id)
                if task:
                    TASKS_SUBMITTED.labels(
                        organization_id=args[0].organization.id,
                        workflow_id=task.workflow_id or "unknown",
                        task_type=task.name
                    ).inc()

                    if result.get("status") == "success":
                        TASKS_COMPLETED.labels(
                            organization_id=args[0].organization.id,
                            workflow_id=task.workflow_id or "unknown",
                            task_type=task.name,
                            status="success"
                        ).inc()
                    else:
                        TASKS_COMPLETED.labels(
                            organization_id=args[0].organization.id,
                            workflow_id=task.workflow_id or "unknown",
                            task_type=task.name,
                            status="failed"
                        ).inc()

                    TASK_DURATION.labels(
                        organization_id=args[0].organization.id,
                        workflow_id=task.workflow_id or "unknown",
                        task_type=task.name
                    ).observe(duration)

            return result
        except Exception as e:
            TASKS_COMPLETED.labels(
                organization_id=args[0].organization.id,
                workflow_id="unknown",
                task_type="unknown",
                status="failed"
            ).inc()
            raise e
    return wrapper

def track_ai_metrics(func):
    """Decorator til at tracke AI Metrics."""
    def wrapper(*args, **kwargs):
        start_time = time.time()
        try:
            result = func(*args, **kwargs)
            duration = time.time() - start_time

            # Hent model_id fra kwargs
            model_id = kwargs.get("model_id")
            if model_id:
                model = args[0].model_registry.get_model(model_id)
                if model:
                    AI_CALLS.labels(
                        model_id=model.id,
                        provider=model.provider.value,
                        task_type=kwargs.get("task_type", "unknown")
                    ).inc()

                    AI_CALL_DURATION.labels(
                        model_id=model.id,
                        provider=model.provider.value
                    ).observe(duration)

                    # Antag, at result indeholder token_count
                    if "token_count" in result:
                        AI_TOKENS_USED.labels(
                            model_id=model.id,
                            provider=model.provider.value,
                            token_type="input"
                        ).inc(result["token_count"]["input"])
                        AI_TOKENS_USED.labels(
                            model_id=model.id,
                            provider=model.provider.value,
                            token_type="output"
                        ).inc(result["token_count"]["output"])

            return result
        except Exception as e:
            AI_CALLS.labels(
                model_id=kwargs.get("model_id", "unknown"),
                provider="unknown",
                task_type="unknown"
            ).inc()
            raise e
    return wrapper
