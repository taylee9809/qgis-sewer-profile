# -*- coding: utf-8 -*-
import os
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction


class SewerProfilePlugin(object):
    def __init__(self, iface):
        self.iface = iface
        self.dock = None
        self.action = None

    def initGui(self):
        icon = QIcon(os.path.join(os.path.dirname(__file__), 'icon.svg'))
        self.action = QAction(icon, '종단도 (Sewer Profile)', self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.toggled.connect(self.toggle)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu('Sewer Profile', self.action)

    def toggle(self, on):
        if on:
            if self.dock is None:
                from .dock import ProfileDock
                self.dock = ProfileDock(self.iface, self.iface.mainWindow())
                self.iface.addDockWidget(Qt.BottomDockWidgetArea, self.dock)
                self.dock.visibilityChanged.connect(self._vis)
            self.dock.show()
        elif self.dock is not None:
            self.dock.hide()

    def _vis(self, v):
        if self.action.isChecked() != v:
            self.action.blockSignals(True)
            self.action.setChecked(v)
            self.action.blockSignals(False)

    def unload(self):
        if self.dock is not None:
            self.dock.cleanup()
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
            self.dock = None
        self.iface.removePluginMenu('Sewer Profile', self.action)
        self.iface.removeToolBarIcon(self.action)
