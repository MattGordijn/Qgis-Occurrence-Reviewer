def classFactory(iface):
    from .plugin import Reviewer
    return Reviewer(iface)
