"""Rapport og statistik: a system role without a language model (decision 43).

The numbers the project manager reports from and the board decides on are
computed here, deterministically, from the milestone state: the job records
of every role and the measurements of every package line ("Hvad der måles"
in the completion plan). Nothing here is estimated; a value that was not
measured is ``None``, not zero.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from typing import Any

STATISTICS_VERSION = 1


def _jobs(state: Mapping[str, Any]) -> Iterable[Mapping[str, Any]]:
    for sprint in state.get("sprints") or []:
        for result in (sprint.get("packages") or {}).values():
            yield from result.get("agent_jobs") or []
            earlier = result.get("earlier") or {}
            yield from earlier.get("agent_jobs") or []
    yield from (state.get("milestone_review") or {}).get("agent_jobs") or []


def _results(state: Mapping[str, Any]) -> Iterable[tuple[int, str, Mapping[str, Any]]]:
    for sprint in state.get("sprints") or []:
        for task_id, result in (sprint.get("packages") or {}).items():
            yield sprint["sprint"], task_id, result


def _tokens(usage: Mapping[str, Any]) -> tuple[int | None, int | None]:
    def first(*keys: str) -> int | None:
        for key in keys:
            if usage.get(key) is not None:
                return int(usage[key])
        return None

    return first("input_tokens", "prompt_tokens"), first(
        "output_tokens", "completion_tokens"
    )


def _rate(values: list[bool | None]) -> float | None:
    measured = [v for v in values if v is not None]
    return round(sum(measured) / len(measured), 3) if measured else None


def _add(total: float | None, value: float | None) -> float | None:
    if value is None:
        return total
    return (total or 0) + value


def milestone_statistics(state: Mapping[str, Any]) -> dict[str, Any]:
    """Statistics per role and producer, per prompt version and per package."""
    by_agent: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "jobs": 0,
            "input_tokens": None,
            "output_tokens": None,
            "cost_usd": None,
        }
    )
    by_prompt: dict[str, int] = defaultdict(int)
    for job in _jobs(state):
        agent = job.get("agent") or {}
        key = (str(job.get("role")), str(agent.get("brand")))
        row = by_agent[key]
        row["jobs"] += 1
        inp, out = _tokens(job.get("usage") or {})
        row["input_tokens"] = _add(row["input_tokens"], inp)
        row["output_tokens"] = _add(row["output_tokens"], out)
        row["cost_usd"] = _add(
            row["cost_usd"], (job.get("usage") or {}).get("cost_usd")
        )
        for ref in str(job.get("prompt_version") or "").split(";"):
            if ref:
                by_prompt[ref] += 1

    packages = []
    by_coder: dict[tuple[str, str], dict[str, list]] = defaultdict(
        lambda: defaultdict(list)
    )
    task_types = {
        t: p.get("task_type") for t, p in (state.get("packages") or {}).items()
    }
    for sprint, task_id, result in _results(state):
        measured = (result.get("package_outcome") or {}).get("measurements") or {}
        packages.append(
            {
                "sprint": sprint,
                "work_package": task_id,
                "task_type": task_types.get(task_id),
                "status": result.get("status"),
                "rechecked": bool(result.get("rechecked")),
                "redelivered": bool(result.get("redelivered")),
                **measured,
            }
        )
        delivered = result.get("delivered_by") or {}
        if delivered:
            row = by_coder[(str(delivered.get("brand")), str(task_types.get(task_id)))]
            for name in (
                "fact_check_passed_first_try",
                "level1_passed_first_try",
                "security_passed_first_try",
                "level2_passed_first_try",
            ):
                row[name].append(measured.get(name))
            row["rework_rounds"].append(measured.get("rework_rounds"))

    def total(name: str) -> int | None:
        values = [p.get(name) for p in packages if p.get(name) is not None]
        return sum(values) if values else None

    return {
        "statistics_version": STATISTICS_VERSION,
        "packages": {
            "runs": len(packages),
            "merged": sum(1 for p in packages if p["status"] == "merged"),
            "rechecked": sum(1 for p in packages if p["rechecked"]),
            "redelivered": sum(1 for p in packages if p["redelivered"]),
            "fact_check_passed_first_try": _rate(
                [p.get("fact_check_passed_first_try") for p in packages]
            ),
            "level1_passed_first_try": _rate(
                [p.get("level1_passed_first_try") for p in packages]
            ),
            "security_passed_first_try": _rate(
                [p.get("security_passed_first_try") for p in packages]
            ),
            "level2_passed_first_try": _rate(
                [p.get("level2_passed_first_try") for p in packages]
            ),
            "rework_rounds": total("rework_rounds"),
            "discarded_attempts": total("discarded_attempts"),
            "invented_references": total("invented_references"),
            "out_of_scope_changes": total("out_of_scope_changes"),
            "secrets_found": total("secrets_found"),
            "rejected_reviewer_findings": total("rejected_reviewer_findings"),
            "assumptions": total("assumptions"),
            "detail": packages,
        },
        "by_role_and_producer": [
            {"role": role, "brand": brand, **row}
            for (role, brand), row in sorted(by_agent.items())
        ],
        "by_prompt_version": dict(sorted(by_prompt.items())),
        "by_coder_and_task_type": [
            {
                "brand": brand,
                "task_type": task_type,
                "deliveries": len(row["rework_rounds"]),
                "level2_passed_first_try": _rate(row["level2_passed_first_try"]),
                "fact_check_passed_first_try": _rate(
                    row["fact_check_passed_first_try"]
                ),
                "rework_rounds": sum(v for v in row["rework_rounds"] if v is not None),
            }
            for (brand, task_type), row in sorted(by_coder.items())
        ],
    }
