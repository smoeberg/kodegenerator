import re
import logging
from typing import Dict, Any, List, Optional, Tuple

logger = logging.getLogger(__name__)

class DiagnosticResult:
    def __init__(self, error_type: str, message: str, file_path: Optional[str], line_no: Optional[int], details: str):
        self.error_type = error_type
        self.message = message
        self.file_path = file_path
        self.line_no = line_no
        self.details = details

class DiagnosticLoop:
    def __init__(self, max_iterations: int = 4):
        self.max_iterations = max_iterations

    def analyze_traceback(self, traceback_output: str) -> DiagnosticResult:
        """
        Parses pytest/Python tracebacks and extracts error type, message, file, line number, and details.
        """
        lines = traceback_output.splitlines()
        error_type = "UnknownError"
        message = ""
        file_path = None
        line_no = None
        
        # Look for standard python exception line at the end or near assertion failures
        # e.g., AssertionError: assert 1 == 2
        # E   AssertionError: assert 1 == 2
        for line in reversed(lines):
            match = re.match(r"^\s*([A-Za-z0-9_]+Error|[A-Za-z0-9_]+Exception):\s*(.*)$", line.strip())
            if match:
                error_type = match.group(1)
                message = match.group(2)
                break
            # Pytest specific failure lines
            match_e = re.match(r"^E\s+([A-Za-z0-9_]+Error|[A-Za-z0-9_]+Exception):\s*(.*)$", line.strip())
            if match_e:
                error_type = match_e.group(1)
                message = match_e.group(2)
                break

        # Extract file and line info from traceback headers
        # e.g., File "/path/to/file.py", line 42, in test_func
        file_pattern = re.compile(r'File "([^"]+)", line (\d+), in')
        for line in lines:
            f_match = file_pattern.search(line)
            if f_match:
                file_path = f_match.group(1)
                try:
                    line_no = int(f_match.group(2))
                except ValueError:
                    pass

        return DiagnosticResult(
            error_type=error_type,
            message=message,
            file_path=file_path,
            line_no=line_no,
            details=traceback_output
        )

    def generate_targeted_feedback(self, diagnostic: DiagnosticResult) -> str:
        """
        Formulates a surgical prompt to the implementation model based on diagnostic results.
        """
        loc_str = f" in file {diagnostic.file_path} around line {diagnostic.line_no}" if diagnostic.file_path else ""
        return (
            f"Test failed with {diagnostic.error_type}: {diagnostic.message}{loc_str}. "
            f"Fix the code issue precisely without altering public APIs or test requirements. "
            f"Ensure all assertions pass."
        )

    def should_retry(self, attempt: int, previous_errors: List[str], current_error: str) -> Tuple[bool, str]:
        """
        Determines whether to retry based on attempt count and circular error detection.
        """
        if attempt >= self.max_iterations:
            return False, f"Max iterations ({self.max_iterations}) reached. Failing closed."
        
        # Detect circular / repeating errors
        if current_error in previous_errors:
            # Check if it repeated more than twice
            count = previous_errors.count(current_error)
            if count >= 2:
                return False, f"Circular error detected: '{current_error}' repeated {count} times. Failing closed to prevent deadlock."

        return True, "Proceed with repair iteration."
