import os
import tempfile
import pytest
from scripts.ci_merge_gate import MergeGateChecker

def test_merge_gate_sandbox_root_bind_violation():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create a file with dangerous root bind
        proc_path = os.path.join(tmpdir, "process.py")
        os.makedirs(os.path.dirname(proc_path), exist_ok=True)
        with open(proc_path, "w") as f:
            f.write('bwrap_args = ["--ro-bind", "/", "/"]\n')

        checker = MergeGateChecker(repo_dir=tmpdir)
        checker.check_sandbox_root_bind(["process.py"])
        assert len(checker.errors) > 0
        assert any("SECURITY VIOLATION (Rule 1)" in err for err in checker.errors)

def test_merge_gate_ghost_file_violation():
    with tempfile.TemporaryDirectory() as tmpdir:
        checker = MergeGateChecker(repo_dir=tmpdir)
        # file in list but not created on disk
        checker.check_ghost_commits(["services/ghost.py"])
        assert len(checker.errors) > 0
        assert any("HALLUCINATION VIOLATION (Rule 2)" in err for err in checker.errors)

def test_merge_gate_dummy_test_violation():
    with tempfile.TemporaryDirectory() as tmpdir:
        test_file = os.path.join(tmpdir, "test_dummy.py")
        with open(test_file, "w") as f:
            f.write("def test_something():\n    assert True\n\ndef test_pass():\n    pass\n")

        checker = MergeGateChecker(repo_dir=tmpdir)
        checker.check_test_coverage_and_dummies(["test_dummy.py"])
        assert len(checker.errors) >= 2
        assert any("DUMMY TEST VIOLATION (Rule 3)" in err for err in checker.errors)

def test_merge_gate_success_case():
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create valid prod file
        services_dir = os.path.join(tmpdir, "services")
        os.makedirs(services_dir, exist_ok=True)
        prod_file = os.path.join(services_dir, "auth.py")
        with open(prod_file, "w") as f:
            f.write("def verify(): return True\n")

        # Create valid test file
        tests_dir = os.path.join(tmpdir, "tests")
        os.makedirs(tests_dir, exist_ok=True)
        test_file = os.path.join(tests_dir, "test_auth.py")
        with open(test_file, "w") as f:
            f.write("def test_verify():\n    from services.auth import verify\n    assert verify() is True\n")

        checker = MergeGateChecker(repo_dir=tmpdir)
        files = ["services/auth.py", "tests/test_auth.py"]
        checker.check_sandbox_root_bind(files)
        checker.check_ghost_commits(files)
        checker.check_test_coverage_and_dummies(files)
        
        assert len(checker.errors) == 0
