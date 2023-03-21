"""
    Creates static class for loading icons and pixmaps that can be used in multiple modules.
"""
import os

from PyQt6 import QtGui

basedir = os.path.dirname(__file__)

class GtImages :
    """ Static class holding png files that are loaded into icons and pixmaps. """

    _red_pixmap = None
    _red_icon = None
    _red_button_icon = None
    _green_pixmap = None
    _green_icon = None
    _green_button_icon = None

    @staticmethod
    def create_images():
        """ Load the png files and initialize the static data. """
        GtImages._red_pixmap = QtGui.QPixmap(os.path.join(basedir, './icons/led_red.png'))
        GtImages._red_icon = QtGui.QIcon(GtImages._red_pixmap)
        red_button_pixmap = QtGui.QPixmap(os.path.join(basedir, './icons/red_button.png'))
        GtImages._red_button_icon = QtGui.QIcon(red_button_pixmap)
        GtImages._green_pixmap = QtGui.QPixmap(os.path.join(basedir,'./icons/led_green.png'))
        GtImages._green_icon = QtGui.QIcon(GtImages._green_pixmap)
        green_button_pixmap = QtGui.QPixmap(os.path.join(basedir,'./icons/green_button.png'))
        GtImages._green_button_icon = QtGui.QIcon(green_button_pixmap)

    @staticmethod
    def red_pixmap():
        """ Initialize the static data and return the red pixmap """
        if GtImages._red_pixmap is None:
            GtImages.create_images()
        return GtImages._red_pixmap

    @staticmethod
    def red_icon():
        """ Initialize the static data and return the red icon """
        if GtImages._red_pixmap is None:
            GtImages.create_images()
        return GtImages._red_icon

    @staticmethod
    def red_button_icon():
        """ Initialize the static data and return the red button icon """
        if GtImages._red_pixmap is None:
            GtImages.create_images()
        return GtImages._red_button_icon

    @staticmethod
    def green_pixmap():
        """ Initialize the static data and return the green pixmap """
        if GtImages._red_pixmap is None:
            GtImages.create_images()
        return GtImages._green_pixmap

    @staticmethod
    def green_icon():
        """ Initialize the static data and return the green icon """
        if GtImages._red_pixmap is None:
            GtImages.create_images()
        return GtImages._green_icon

    @staticmethod
    def green_button_icon():
        """ Initialize the static data and return the green button icon """
        if GtImages._red_pixmap is None:
            GtImages.create_images()
        return GtImages._green_button_icon
