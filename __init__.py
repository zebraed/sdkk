"""
Driven key creation, management, and import/export tool for Maya.
"""
__author__ = "zebraed"
__copyright__ = "Copyright 2019-2026, zebraed"
__license__ = "MIT"
__email__ = "contact@sarygamysh.com"
__status__ = "Stable"
__version__ = "2.0.0"

import importlib
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .command.animation import list_animated_plugs, read_animation_as_driven_key  # noqa: F401
    from .command.animcurve import verify_round_trip  # noqa: F401
    from .command.drivenkey import (  # noqa: F401
        DrivenKey,
        find_driven_key,
        list_driven_keys,
        plan_driven_keys,
    )
    from .core.state import (  # noqa: F401
        ApplyResult,
        ConflictPolicy,
        MirrorCheckItem,
        MirrorStatus,
        PlanItem,
        PlanStatus,
        Role,
        Status,
    )
    from .core.model import MirrorRule, NamespaceMapper, ReplaceMapper, SwapMapper, compose  # noqa: F401
    from .core.serialize import DocumentError, read_document  # noqa: F401
    from .ops import (  # noqa: F401
        apply_plan,
        check_mirrored_driven_keys,
        cleanup_driven_keys,
        convert_animation_to_driven_keys,
        copy_driven_keys,
        delete_all_driven_keys,
        delete_driven_key,
        delete_driven_keys,
        export_driven_keys,
        import_driven_keys,
        mirror_driven_keys,
        move_driven_keys,
        remove_driven_keys_at,
        remove_key,
        rename_driven_keys,
        retarget_driven_keys,
        set_driven_key,
        set_driven_keys,
    )
    from .ui import show  # noqa: F401

_EXPORTS = {
    "set_driven_key": "ops",
    "set_driven_keys": "ops",
    "show": "ui",
    "convert_animation_to_driven_keys": "ops",
    "remove_key": "ops",
    "move_driven_keys": "ops",
    "remove_driven_keys_at": "ops",
    "delete_driven_key": "ops",
    "delete_driven_keys": "ops",
    "delete_all_driven_keys": "ops",
    "rename_driven_keys": "ops",
    "copy_driven_keys": "ops",
    "mirror_driven_keys": "ops",
    "retarget_driven_keys": "ops",
    "export_driven_keys": "ops",
    "import_driven_keys": "ops",
    "apply_plan": "ops",
    "check_mirrored_driven_keys": "ops",
    "cleanup_driven_keys": "ops",
    "list_driven_keys": "command.drivenkey",
    "find_driven_key": "command.drivenkey",
    "plan_driven_keys": "command.drivenkey",
    "list_animated_plugs": "command.animation",
    "read_animation_as_driven_key": "command.animation",
    "read_document": "core.serialize",
    "verify_round_trip": "command.animcurve",
    # types
    "ApplyResult": "core.state",
    "ConflictPolicy": "core.state",
    "DocumentError": "core.serialize",
    "DrivenKey": "command.drivenkey",
    "MirrorCheckItem": "core.state",
    "MirrorRule": "core.model",
    "MirrorStatus": "core.state",
    "NamespaceMapper": "core.model",
    "PlanItem": "core.state",
    "PlanStatus": "core.state",
    "ReplaceMapper": "core.model",
    "Role": "core.state",
    "Status": "core.state",
    "SwapMapper": "core.model",
    "compose": "core.model",
}

__all__ = list(_EXPORTS)


def __getattr__(name):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    return getattr(importlib.import_module(f".{_EXPORTS[name]}", __name__), name)


def __dir__():
    return sorted(set(globals()) | set(__all__))


def Reload():
    import sys
    for k in list(sys.modules):
        if k.startswith(__name__):
            del sys.modules[k]
    print(f"{__name__} Reloaded.")
