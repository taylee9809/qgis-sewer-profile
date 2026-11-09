# -*- coding: utf-8 -*-
"""화면 언어 — QGIS 언어가 한국어면 한국어, 아니면 영어.

문구는 쓰는 자리에서 tr('한국어', 'English') 로 짝지어 둔다(번역표가 따로 놀지 않게).
언어는 QGIS 를 켤 때 정해지므로 모듈을 불러올 때 한 번만 본다.
"""


def _locale():
    try:
        from qgis.core import QgsApplication
        loc = QgsApplication.locale()
        if loc:
            return loc
    except Exception:
        pass
    try:
        from qgis.PyQt.QtCore import QLocale
        return QLocale.system().name()
    except Exception:
        return 'ko'


KO = str(_locale()).lower().startswith('ko')


def tr(ko, en):
    return ko if KO else en
