"""
Selects nodes in the scene for a row the user clicked, and tells what to show when none exists.

クリックした行のノードをシーンで選択し、1つも見つからないときに出す警告を返す
"""
from .. import service
from ..i18n import tr


def select_nodes(names):
    """Select the nodes that exist in the scene.

    シーンにあるノードを選択する

    Args:
        names (Sequence[str]): ノード名。シーンにないものは飛ばす

    Returns:
        Optional[str]: 1つも見つからなかったときの警告の文字列。選択できたらNone
    """
    if service.select_existing_nodes(names):
        return None

    short_names = ", ".join(name.rpartition("|")[2] for name in names)
    return "⚠ " + tr("Not found in the scene: {names}", names=short_names)
