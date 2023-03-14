import os

from PyQt6 import QtGui

basedir = os.path.dirname(__file__)

class GtImages :

    _red_pixmap = None
    _red_icon = None
    _red_button_icon = None
    _green_pixmap = None
    _green_icon = None
    _green_button_icon = None

    @staticmethod
    def create_images():
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
        if GtImages._red_pixmap == None:
            GtImages.create_images()
        return GtImages._red_pixmap

    @staticmethod 
    def red_icon():
        if GtImages._red_pixmap == None:
            GtImages.create_images()
        return GtImages._red_icon

    @staticmethod
    def red_button_icon():
        if GtImages._red_pixmap == None:
            GtImages.create_images()
        return GtImages._red_button_icon

    @staticmethod
    def green_pixmap():
        if GtImages._red_pixmap == None:
            GtImages.create_images()
        return GtImages._green_pixmap

    @staticmethod
    def green_icon():
        if GtImages._red_pixmap == None:
            GtImages.create_images()
        return GtImages._green_icon

    @staticmethod
    def green_button_icon():
        if GtImages._red_pixmap == None:
            GtImages.create_images()
        return GtImages._green_button_icon






