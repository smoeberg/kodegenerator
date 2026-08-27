import json
import time
from typing import Dict, Any, List

class ProductivityBenchmark:
    def __init__(self):
        self.benchmark_results: List[Dict[str, Any]] = []

    def run_task_benchmark(self, task_name: str, success: bool, iterations_needed: int, duration_seconds: float, token_cost: int, human_baseline_hours: float) -> Dict[str, Any]:
        """
        Evaluates a task's performance and calculates productivity multiplier.
        """
        # Human hours vs AI execution hours (duration_seconds / 3600)
        ai_hours = max(duration_seconds / 3600.0, 0.001) # Avoid division by zero
        multiplier = round(human_baseline_hours / ai_hours, 2) if success else 0.0

        result = {
            "task_name": task_name,
            "success": success,
            "iterations_needed": iterations_needed,
            "duration_seconds": round(duration_seconds, 3),
            "token_cost": token_cost,
            "estimated_human_hours_saved": round(human_baseline_hours - ai_hours, 2) if success else 0.0,
            "productivity_multiplier": multiplier
        }
        self.benchmark_results.append(result)
        return result

    def generate_report(self) -> Dict[str, Any]:
        """
        Generates aggregated JSON report and summary stats.
        """
        total_tasks = len(self.benchmark_results)
        successful_tasks = sum(1 for r in self.benchmark_results if r["success"])
        total_tokens = sum(r["token_cost"] for r in self.benchmark_results)
        total_hours_saved = sum(r["estimated_human_hours_saved"] for r in self.benchmark_results)
        avg_multiplier = sum(r["productivity_multiplier"] for r in self.benchmark_results) / max(total_tasks, 1)

        summary = {
            "total_tasks": total_tasks,
            "successful_tasks": successful_tasks,
            "success_rate": round(successful_tasks / max(total_tasks, 1) * 100, 1),
            "total_tokens_consumed": total_tokens,
            "total_human_hours_saved": round(total_hours_saved, 2),
            "average_productivity_multiplier": round(avg_multiplier, 2),
            "tasks": self.benchmark_results
        }
        return summary

    def generate_markdown_table(self) -> str:
        """
        Generates a markdown table of the benchmark results.
        """
        report = self.generate_report()
        lines = [
            "### 📊 Autonomous Productivity Benchmark Report",
            f"**Success Rate:** {report['success_rate']}% ({report['successful_tasks']}/{report['total_tasks']} tasks)",
            f"**Total Human Hours Saved:** {report['total_human_hours_saved']} hrs",
            f"**Average Productivity Multiplier:** {report['average_productivity_multiplier']}x",
            "",
            "| Task Name | Success | Iterations | Duration (s) | Tokens | Hours Saved | Multiplier |",
            "| :--- | :---: | :---: | :---: | :---: | :---: | :---: |"
        ]
        for t in report["tasks"]:
            status = "✅" if t["success"] else "❌"
            lines.append(
                f"| {t['task_name']} | {status} | {t['iterations_needed']} | {t['duration_seconds']}s | "
                f"{t['token_cost']} | {t['estimated_human_hours_saved']}h | {t['productivity_multiplier']}x |"
            )
        return "\n".join(lines)
