# main.py (Udvidet)
from domain.task import Task, TaskStatus, TaskPriority
from domain.artifact import Artifact, ArtifactType, ArtifactState
import asyncio

async def main():
    # ... (Forrige kode for at oprette organisation, actors, etc.)

    # Opret en Intent
    intent = Intent(
        id="intent_oauth2",
        goal="Implement OAuth2 Authentication",
        priority=IntentPriority.HIGH,
        required_capabilities=["python", "fastapi", "security"],
        constraints={"security_level": "high"},
        creator=gpt5_actor,
        organization=organization
    )

    # Indsend Intent med Feature Development Template
    workflow = dor.submit_intent_with_template(
        intent=intent,
        actor=gpt5_actor,
        template_id="feature_development"
    )

    if workflow:
        print(f"Workflow started: {workflow.id}")

        # Hent den første Task
        pending_tasks = dor.workflow_engine.task_scheduler.get_pending_tasks()
        if pending_tasks:
            first_task = pending_tasks[0]
            print(f"First task: {first_task.name} (Status: {first_task.status.name})")

            # Tildel Tasken til GPT-5
            dor.workflow_engine.task_scheduler.assign_task(first_task, gpt5_actor)
            first_task.start()

            # Udfør Tasken med AI Executor
            result = await dor.execute_task(first_task.id)
            print(f"Task execution result: {result}")

            if result.get("status") == "success":
                print(f"Task completed successfully! Output: {result.get('output', '')[:100]}...")

                # Hent det genererede Artefakt
                artifact_id = result.get("artifact_id")
                if artifact_id:
                    artifact = dor.get_artifact(artifact_id)
                    print(f"Generated artifact: {artifact.id} (Type: {artifact.artifact_type.value})")

                    # Indsend Artefaktet til review
                    dor.workflow_engine.artifact_manager.submit_artifact(artifact_id, gpt5_actor)

                    # Skift Workflow-tilstand til REVIEW
                    dor.workflow_engine.transition_workflow(
                        workflow.id,
                        WorkflowState.REVIEW,
                        gpt5_actor
                    )
                    print(f"Workflow transitioned to: {workflow.current_state.name.value}")
            else:
                print(f"Task failed: {result.get('error', 'Unknown error')}")

    # Luk database-session
    db.close()

# Kør main()
asyncio.run(main())
