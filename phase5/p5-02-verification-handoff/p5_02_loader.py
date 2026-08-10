"""Load P5-00 explicitly without colliding with the P5-01 loader."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

MODULE_NAME = "eira_dor_p5_00_contract_from_p5_02"


def load_p5_00() -> ModuleType:
    existing = sys.modules.get(MODULE_NAME)
    if existing is not None:
        return existing
    root = Path(__file__).resolve().parents[1]
    package_dir = root / "p5-00-ai-work-product-contract"
    path = package_dir / "contract.py"
    spec = importlib.util.spec_from_file_location(
        MODULE_NAME, path, submodule_search_locations=[str(package_dir)]
    )
    if spec is None or spec.loader is None:
        raise ImportError("unable to load P5-00 contract")
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module
