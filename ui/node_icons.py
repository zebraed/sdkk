"""
Icons of Maya nodes, the same as the Outliner shows.

アウトライナーに出るのと同じ、Mayaのノードのアイコン
"""
from Qt import QtGui

_cache = {}


def get_node_icon(resource):
    """Return the icon of a resource name. An empty icon if there is none.

    リソース名のアイコンを返す。なければ空のアイコン

    Args:
        resource (Optional[str]): Mayaのリソース名（":/out_joint.png"など）

    Returns:
        QtGui.QIcon: アイコン
    """
    if resource is None:
        return QtGui.QIcon()

    if resource not in _cache:
        _cache[resource] = QtGui.QIcon(resource)

    return _cache[resource]
