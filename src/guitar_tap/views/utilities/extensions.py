"""
Reusable Qt widget helpers and free-function utilities.

Mirrors Swift's Extensions.swift — extension methods and small helper
functions that are used across multiple view files.

These helpers are extracted from guitar_tap.py so that the mixin files
can import them without importing the entire MainWindow module.
"""

from __future__ import annotations

from PySide6 import QtWidgets


def vsep() -> QtWidgets.QFrame:
    """Thin vertical separator for use inside horizontal toolbars."""
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.VLine)
    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return sep


def hsep() -> QtWidgets.QFrame:
    """Thin horizontal separator for use between vertical sections."""
    sep = QtWidgets.QFrame()
    sep.setFrameShape(QtWidgets.QFrame.Shape.HLine)
    sep.setFrameShadow(QtWidgets.QFrame.Shadow.Sunken)
    return sep
