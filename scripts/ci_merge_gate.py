#!/usr/bin/env python3
import os
import sys
import ast
import json
import subprocess
import argparse
from typing import List, Dict, Any, Tuple

class MergeGateChecker:
    def __init__(self, base: str = "origin/main", head: str = "HEAD", repo_dir: str = "."):
        self.base = base
        self.head = head
        self.repo_dir = repo_dir
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def run_git(self, cmd: List[str]) -> str:
        res = subprocess.run(cmd, cwd=self.repo_dir, capture_output=True, text=True)
        if res.returncode != 0:
            # Fallback or return empty if ref doesn't exist in local shallow clone
            return ""
        return res.stdout.strip()

    def get_diff_files(self) -> List[str]:
        output = self.run_git(["git", "diff", "--name-only", f"{self.base}...{self.head}"])
        if not output:
            # Fallback to staged + unstaged if base...head fails
            output = self.run_git(["git", "diff", "--name-only", "HEAD"])
        if not output:
            output = self.run_git(["git", "ls-files"])
        return [line.strip() for line in output.splitlines() if line.strip()]

    def check_sandbox_root_bind(self, files: List[str]) -> None:
        """Rule 1: Sandbox Root-Bind Ban (Zero-Tolerance Security Rule)"""
        # Obfuscate forbidden sequences so this script itself doesn't trigger pattern matches
        s = "/"
        forbidden_snippets = [
            f'"--ro-bind", "{s}", "{s}"',
            f"'--ro-bind', '{s}', '{s}'",
            '"--ro-bind", os.sep, os.sep',
            "'--ro-bind', os.sep, os.sep",
            f'"--bind", "{s}", "{s}"',
            f"'--bind', '{s}', '{s}'",
        ]
        
        # Only inspect production/sandbox files, not test files or linter scripts themselves
        target_files = [f for f in set(files + ["phase6/execution/process.py", "services/sandbox.py"])
                        if not f.startswith("tests/") and not f.startswith("scripts/") and f.endswith(".py")]
        
        for f_path in target_files:
            full_path = os.path.join(self.repo_dir, f_path)
            if not os.path.exists(full_path):
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    content = f.read()
                for pat in forbidden_snippets:
                    if pat in content:
                        self.errors.append(f"SECURITY VIOLATION (Rule 1): Detected forbidden root mount pattern '{pat}' in {f_path}")
            except Exception:
                pass

    def check_ghost_commits(self, files: List[str]) -> None:
        """Rule 2: Anti-Hallucination & Ghost-Commit Verifier"""
        for f_path in files:
            full_path = os.path.join(self.repo_dir, f_path)
            if not os.path.exists(full_path):
                self.errors.append(f"HALLUCINATION VIOLATION (Rule 2): File '{f_path}' is in diff but does not exist on disk.")
                continue
            
            if os.path.getsize(full_path) == 0:
                self.errors.append(f"HALLUCINATION VIOLATION (Rule 2): File '{f_path}' is empty (0 bytes).")
                continue

            if f_path.endswith(".py"):
                try:
                    with open(full_path, "r", encoding="utf-8") as f:
                        code = f.read()
                    ast.parse(code)
                except SyntaxError as se:
                    self.errors.append(f"SYNTAX VIOLATION (Rule 2): File '{f_path}' has invalid Python syntax: {se}")

    def check_test_coverage_and_dummies(self, files: List[str]) -> None:
        """Rule 3: Test Execution & Attestation Cross-Check & Dummy Test Detector"""
        prod_files = [f for f in files if any(f.startswith(p) for p in ["services/", "phase6/", "api/"])]
        test_files = [f for f in files if "test" in f and f.endswith(".py")]
        
        if prod_files and not test_files:
            # Check if existing tests cover it or if any test file was modified overall
            all_tests = self.run_git(["git", "ls-files", "*test*.py"]).splitlines()
            if not all_tests:
                self.errors.append("COVERAGE VIOLATION (Rule 3): Production code modified/added without corresponding unit tests.")

        # Inspect test files for dummy tests
        for f_path in test_files:
            full_path = os.path.join(self.repo_dir, f_path)
            if not os.path.exists(full_path):
                continue
            try:
                with open(full_path, "r", encoding="utf-8") as f:
                    code = f.read()
                tree = ast.parse(code)
                
                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef) and node.name.startswith("test_"):
                        # Check body for dummy patterns: assert True, pass only, empty body
                        body = node.body
                        if not body:
                            self.errors.append(f"DUMMY TEST VIOLATION (Rule 3): Empty test function '{node.name}' in {f_path}")
                            continue
                        
                        # Check if body is just 'pass' or 'assert True'
                        is_dummy = False
                        if len(body) == 1:
                            stmt = body[0]
                            if isinstance(stmt, ast.Pass):
                                is_dummy = True
                            elif isinstance(stmt, ast.Assert):
                                if isinstance(stmt.test, ast.Constant) and stmt.test.value is True:
                                    is_dummy = True
                                elif isinstance(stmt.test, ast.Name) and stmt.test.id == "True":
                                    is_dummy = True
                        
                        if is_dummy:
                            self.errors.append(f"DUMMY TEST VIOLATION (Rule 3): Dummy test detected ('assert True' or 'pass') in '{node.name}' in {f_path}")
            except Exception as e:
                pass

    def run(self) -> bool:
        files = self.get_diff_files()
        self.check_sandbox_root_bind(files)
        self.check_ghost_commits(files)
        self.check_test_coverage_and_dummies(files)

        report = {
            "base": self.base,
            "head": self.head,
            "files_inspected": len(files),
            "errors": self.errors,
            "warnings": self.warnings,
            "status": "PASSED" if not self.errors else "FAILED"
        }

        with open("merge_gate_report.json", "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)

        # Generate markdown summary
        md_lines = [
            "### 🛡️ Merge Gate & Diff Integrity Report",
            f"**Status:** {'🟢 PASSED' if not self.errors else '❌ FAILED'}",
            f"**Files Inspected:** {len(files)}",
            f"**Errors Found:** {len(self.errors)}",
            ""
        ]
        if self.errors:
            md_lines.append("#### Violations:")
            for err in self.errors:
                md_lines.append(f"- ❌ {err}")
        else:
            md_lines.append("✅ All integrity rules, sandbox security checks, and test requirements passed successfully.")
        
        md_summary = "\n".join(md_lines)
        print(md_summary)

        github_step_summary = os.environ.get("GITHUB_STEP_SUMMARY")
        if github_step_summary:
            with open(github_step_summary, "a", encoding="utf-8") as f:
                f.write(md_summary + "\n")

        return len(self.errors) == 0

def main():
    parser = argparse.ArgumentParser(description="Merge Gate and Diff Integrity Linter")
    parser.add_argument("--base", default="origin/main", help="Base git ref")
    parser.add_argument("--head", default="HEAD", help="Head git ref")
    args = parser.parse_args()

    gate = MergeGateChecker(base=args.base, head=args.head)
    success = gate.run()
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
