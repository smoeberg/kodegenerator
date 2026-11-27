"""Rapport og statistik: computed, never estimated."""

from execution.statistics import milestone_statistics


def job(role, brand, prompt, **usage):
    return {
        "role": role,
        "agent": {"brand": brand},
        "prompt_version": prompt,
        "usage": usage,
    }


def test_numbers_come_from_job_records_and_unmeasured_stays_none() -> None:
    state = {
        "packages": {
            "module-a": {"task_type": "module_http"},
            "module-b": {"task_type": "module_data"},
        },
        "sprints": [
            {
                "sprint": 1,
                "packages": {
                    "module-a": {
                        "status": "merged",
                        "delivered_by": {"brand": "openai"},
                        "agent_jobs": [
                            job(
                                "coder",
                                "openai",
                                "coder/implement_module@v1+a;coder/rework_package@v1+b",
                                input_tokens=10,
                                output_tokens=5,
                                cost_usd=0.5,
                            ),
                            job(
                                "code_auditor",
                                "google",
                                "code_auditor/audit_package@v1+c",
                                prompt_tokens=7,
                                completion_tokens=1,
                            ),
                        ],
                        "package_outcome": {
                            "measurements": {
                                "level2_passed_first_try": False,
                                "rework_rounds": 1,
                                "secrets_found": 0,
                            }
                        },
                    },
                    "module-b": {
                        "status": "waiting",
                        "agent_jobs": [
                            job("coder", "openai", "coder/implement_module@v1+a")
                        ],
                        "package_outcome": {
                            "measurements": {"level2_passed_first_try": None}
                        },
                    },
                },
            }
        ],
    }
    stats = milestone_statistics(state)
    assert stats["packages"]["merged"] == 1 and stats["packages"]["runs"] == 2
    assert stats["packages"]["level2_passed_first_try"] == 0.0  # one measured, one not
    assert stats["packages"]["discarded_attempts"] is None  # never measured is not zero
    coder = next(r for r in stats["by_role_and_producer"] if r["role"] == "coder")
    assert (
        coder["jobs"],
        coder["input_tokens"],
        coder["output_tokens"],
        coder["cost_usd"],
    ) == (2, 10, 5, 0.5)
    auditor = next(
        r for r in stats["by_role_and_producer"] if r["role"] == "code_auditor"
    )
    assert (auditor["input_tokens"], auditor["cost_usd"]) == (7, None)
    assert stats["by_prompt_version"]["coder/implement_module@v1+a"] == 2
    assert stats["by_coder_and_task_type"] == [
        {
            "brand": "openai",
            "task_type": "module_http",
            "deliveries": 1,
            "level2_passed_first_try": 0.0,
            "fact_check_passed_first_try": None,
            "rework_rounds": 1,
        }
    ]
