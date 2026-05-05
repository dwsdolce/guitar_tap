""" Extension of the QSlider to provie independent control of the
slider position and the groove rectangle. The groove rectangle is
used to display the current amplitude of the signal and the slider
is used to define the threshold setting.
"""

from PyQt6 import QtCore, QtWidgets, QtGui

STYLE_SHEET = '''
    QSlider::groove:horizontal {
        border: 1px solid;
        margin: 0px;
    }
    QSlider::handle:horizontal {
        background: red;
        border: 0px solid;
        width: 4px;
    }
    QSlider::handle:horizontal:hover {
        background: #c44;
        border: 0px solid white;
        width: 4px;
    }
'''

# pylint: disable=too-few-public-methods
class ProxyStyle(QtWidgets.QProxyStyle):
    """ Used to redefine the action of clicking in the groove
    rectangle so that the slider immediately moves to the
    click position
    """

    # pylint: disable=invalid-name
    def styleHint(self, hint, opt=None, widget=None, returnData=None):
        """ Required override to define the hint for the style """

        # pylint: disable=invalid-name
        res = super().styleHint(hint, opt, widget, returnData)
        if hint == QtWidgets.QStyle.StyleHint.SH_Slider_AbsoluteSetButtons:
            #res = Qt.MouseButton.LeftButton
            res = 1
        return res

class ThresholdSlider(QtWidgets.QSlider):
    """ Extension of the QSlider to provie independent control of the
    slider position and the groove rectangle. The groove rectangle is
    used to display the current amplitude of the signal and the slider
    is used to define the threshold setting.
    """

    def __init__(self, *args, **kwargs):
        self.volume = 0
        super().__init__(*args, **kwargs)
        self.setStyleSheet(STYLE_SHEET)
        self.setStyle(ProxyStyle())
        self.setMinimum(0)
        self.setMaximum(100)
        self.setValue(50)
        self.setTickPosition(QtWidgets.QSlider.TickPosition.NoTicks)
        self.setTickInterval(10)
        self.setSingleStep(1)
        self.setPageStep(10)

    def set_amplitude(self, value):
        """ Sets the value to use to draw the groove rectangle """

        # Value is 0 to 100
        self.volume = value
        self.update()

    # pylint: disable=invalid-name
    def paintEvent(self, _event):
        """ standard paint event override """

        qp = QtWidgets.QStylePainter(self)
        opt = QtWidgets.QStyleOptionSlider()
        style = self.style()
        self.initStyleOption(opt)

        # draw the groove only
        opt.subControls =  QtWidgets.QStyle.SubControl.SC_SliderGroove

        qp.save()
        grooveRect = style.subControlRect(
                QtWidgets.QStyle.ComplexControl.CC_Slider, opt,
                QtWidgets.QStyle.SubControl.SC_SliderGroove)
        grooveTop = grooveRect.top()
        grooveBottom = grooveRect.bottom()
        grooveLeft = grooveRect.left()
        grooveWidth = (grooveRect.width() * self.volume)//100
        grooveHeight = grooveRect.height()
        qp.setPen(QtCore.Qt.PenStyle.NoPen)
        # Draw the amplitude marker
        grad1 = QtGui.QLinearGradient(grooveWidth/2, grooveTop, grooveWidth/2, grooveBottom)
        grad1.setColorAt(0.0, QtCore.Qt.GlobalColor.cyan)
        grad1.setColorAt(0.7, QtCore.Qt.GlobalColor.blue)
        grad1.setColorAt(1.0, QtCore.Qt.GlobalColor.black)
        qp.setBrush(QtGui.QBrush(grad1))
        qp.drawRect(grooveTop, grooveLeft, grooveWidth, grooveHeight)

        # Draw the tick marks on the amplitude
        qp.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.green, 1, QtCore.Qt.PenStyle.SolidLine))
        nTicks = 50
        for i in range(nTicks):
            x = (grooveRect.width()*i)//nTicks
            if x < grooveRect.width():
                qp.drawLine(x, grooveRect.top(), x, grooveRect.bottom())

        qp.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.green, 2, QtCore.Qt.PenStyle.SolidLine))

        # Draw major tick marks
        nTicks = 10
        for i in range(nTicks):
            x = (grooveRect.width()*i)//nTicks
            if x <= grooveRect.width():
                qp.drawLine(x, grooveRect.top(), x, grooveRect.bottom())

        # Draw recessed border
        qp.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.black, 1, QtCore.Qt.PenStyle.SolidLine))
        qp.drawLine(0, 0, self.width(), 0)
        qp.drawLine(0, 0, 0, self.height())
        qp.setPen(QtGui.QPen(QtCore.Qt.GlobalColor.white, 1, QtCore.Qt.PenStyle.SolidLine))
        qp.drawLine(0, self.height(), self.width(), self.height())
        qp.drawLine(self.width(), 0, self.width(), self.height())



        qp.restore()

        opt.subControls = style.SubControl.SC_SliderHandle
        if self.tickPosition != QtWidgets.QSlider.TickPosition.NoTicks:
            opt.subControls |= style.SubControl.SC_SliderTickmarks
        #opt.activeSubControls = style.SC_SliderHandle
        if self.isSliderDown():
            opt.state |= style.StateFlag.State_Sunken
        qp.drawComplexControl(style.ComplexControl.CC_Slider, opt)
