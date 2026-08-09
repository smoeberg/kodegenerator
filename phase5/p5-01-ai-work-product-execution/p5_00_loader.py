"""Load the hyphenated P5-00 slice as a real package.

P5-00 deliberately has no ``__init__.py`` because pytest treats that file as
a hostile top-level package in the slice layout. P5-01 therefore loads the
explicit public contract module without changing P5-00's import model.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
from types import ModuleType

_MODULE_NAME = "eira_dor_p5_00_contract"


def load_contract_api() -> ModuleType:
    existing = sys.modules.get(_MODULE_NAME)
    if existing is not None:
        return existing

    root = Path(__file__).resolve().parents[1]
    package_dir = root / "p5-00-ai-work-product-contract"
    init_path = package_dir / "contract.py"
    if not init_path.exists():
        raise ImportError(f"P5-00 contract not found: {init_path}")

    spec = importlib.util.spec_from_file_location(
        _MODULE_NAME,
        init_path,
        submodule_search_locations=[str(package_dir)],
    )
    if spec is None or spec.loader is None:
        raise ImportError("unable to construct P5-00 contract loader")
    module = importlib.util.module_from_spec(spec)
    sys.modules[_MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module
