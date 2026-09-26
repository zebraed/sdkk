"""
sdkkパッケージ直下の公開APIのテスト（Maya不要）
"""
import ast
import importlib
import sys

import pytest

from ..core.model import MirrorRule
from ..core.serialize import read_document

package = importlib.import_module("..", __package__)


def read_type_checking_imports():
    # TYPE_CHECKINGのimportを、名前 → モジュールの対応として取り出す
    with open(package.__file__, "r", encoding="utf-8") as stream:
        tree = ast.parse(stream.read())

    for node in tree.body:
        if isinstance(node, ast.If) and getattr(node.test, "id", None) == "TYPE_CHECKING":
            return {alias.name: statement.module for statement in node.body for alias in statement.names}

    raise AssertionError("__init__.py has no TYPE_CHECKING block")


def test_type_checking_imports_match_exports():
    # pylint: disable-next=protected-access
    assert read_type_checking_imports() == package._EXPORTS


def test_names_defined_without_maya_are_returned_without_importing_maya():
    assert package.MirrorRule is MirrorRule
    assert package.read_document is read_document
    assert "maya" not in sys.modules


def test_unknown_name_raises_attribute_error_without_importing_maya():
    with pytest.raises(AttributeError):
        getattr(package, "not_an_api")

    assert "maya" not in sys.modules


def test_dir_lists_exported_names():
    assert {"set_driven_key", "import_driven_keys", "MirrorRule"} <= set(dir(package))
