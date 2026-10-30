"""
pipeline package.

Names are imported lazily so that light-weight modules (for example
``pipeline.convert``, used for archive conversion) can be imported without
pulling in the Adobe/Affinity controllers and their Windows-only dependencies.
"""

import importlib

_LAZY = {
    "AssetScanner": "pipeline.scanner",
    "JobQueue": "pipeline.jobqueue",
    "Job": "pipeline.job",
    "JobStatus": "pipeline.job",
    "AssetProcessor": "pipeline.processor",
    "AssetPackage": "pipeline.asset_package",
    "PackageClassifier": "pipeline.asset_package",
    "FileCategory": "pipeline.asset_package",
    "AssetFile": "pipeline.asset_package",
}

__all__ = list(_LAZY)


def __getattr__(name):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module 'pipeline' has no attribute {name!r}")
    value = getattr(importlib.import_module(module), name)
    globals()[name] = value
    return value
