def classFactory(iface):
    from .plugin import SewerProfilePlugin
    return SewerProfilePlugin(iface)
