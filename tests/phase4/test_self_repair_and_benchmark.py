import pytest
from services.diagnostic_loop import DiagnosticLoop
from services.productivity_benchmark import ProductivityBenchmark

def test_diagnostic_loop_parsing_and_feedback():
    loop = DiagnosticLoop(max_iterations=3)
    
    sample_traceback = """
    Traceback (most recent call last):
      File "/app/services/calculator.py", line 14, in add
        return a - b
    AssertionError: assert 3 == 5
    """
    
    diagnostic = loop.analyze_traceback(sample_traceback)
    assert diagnostic.error_type == "AssertionError"
    assert "assert 3 == 5" in diagnostic.message
    assert diagnostic.file_path == "/app/services/calculator.py"
    assert diagnostic.line_no == 14
    
    feedback = loop.generate_targeted_feedback(diagnostic)
    assert "AssertionError" in feedback
    assert "/app/services/calculator.py" in feedback
    assert "line 14" in feedback

def test_diagnostic_loop_retry_and_deadlock():
    loop = DiagnosticLoop(max_iterations=2)
    
    # First attempt OK to retry
    should, msg = loop.should_retry(attempt=1, previous_errors=[], current_error="KeyError: 'foo'")
    assert should is True
    
    # Max iterations reached -> should not retry
    should, msg = loop.should_retry(attempt=2, previous_errors=["KeyError: 'foo'"], current_error="KeyError: 'foo'")
    assert should is False
    assert "Max iterations" in msg

    # Circular error detection (same error repeated twice)
    should, msg = loop.should_retry(attempt=1, previous_errors=["TypeError: int expected", "TypeError: int expected"], current_error="TypeError: int expected")
    assert should is False
    assert "Circular error detected" in msg

def test_productivity_benchmark_and_report():
    benchmark = ProductivityBenchmark()
    
    res1 = benchmark.run_task_benchmark(
        task_name="Rate Limiter Service",
        success=True,
        iterations_needed=1,
        duration_seconds=45.2,
        token_cost=1250,
        human_baseline_hours=4.0
    )
    assert res1["success"] is True
    assert res1["productivity_multiplier"] > 1.0

    res2 = benchmark.run_task_benchmark(
        task_name="JWT Auth Middleware",
        success=True,
        iterations_needed=2,
        duration_seconds=90.0,
        token_cost=2100,
        human_baseline_hours=6.0
    )
    assert res2["success"] is True

    summary = benchmark.generate_report()
    assert summary["total_tasks"] == 2
    assert summary["successful_tasks"] == 2
    assert summary["success_rate"] == 100.0
    assert summary["total_tokens_consumed"] == 3350

    markdown = benchmark.generate_markdown_table()
    assert "Autonomous Productivity Benchmark Report" in markdown
    assert "Rate Limiter Service" in markdown
    assert "JWT Auth Middleware" in markdown
