"""Integration tests for TaskCompiler + ContextEngine.

Uses a temporary mini-repository with realistic JWT/auth-related surfaces so
signature extraction and prompt-contract compilation can be verified without
network or LLM access.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from services.context_engine import (
    ContextEngine,
    ContextPackage,
    extract_signatures_from_source,
    format_function_signature,
)
from services.task_compiler import (
    AtomicTestSpec,
    CompiledTaskPackage,
    PromptContract,
    RequirementInput,
    TaskCompiler,
    TaskCompilerError,
    split_acceptance_criteria,
)
