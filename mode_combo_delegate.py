"""
    Custom editor for the mode column
"""
from PyQt6 import QtWidgets, QtCore

class ModeComboDelegate(QtWidgets.QStyledItemDelegate):
    """ Provides a combobox for selecting mode values. """
    def __init__(self, parent, items) -> None:
        self.items = items
        super().__init__(parent)

    # pylint: disable=invalid-name
    def createEditor(self,
                     parent: QtWidgets.QWidget,
                     _option: QtWidgets.QStyleOptionViewItem,
                     _index: QtCore.QModelIndex
                    ) -> QtWidgets.QWidget:
        """ Create the editor for the mode column. """
        #print("ModeComboDelegate: createEditor")
        # pylint: disable=attribute-defined-outside-init
        self.editor = QtWidgets.QComboBox(parent)
        self.editor.setStyleSheet("background=-color: white; \n"
                                  "border: 1px solid gray; \n"
                                  "padding: 1px 3px 1px 3px;")
        self.editor.addItems(self.items)
        self.editor.currentIndexChanged.connect(self.currentIndexChanged)
        return self.editor

    def setEditorData(self, editor: QtWidgets.QWidget, index: QtCore.QModelIndex) -> None:
        """ Set the data in the editor from the model data. """
        #print("ModeComboDelegate: setEditorData")
        editor.blockSignals(True) # block signals that are not caused by the user
        editor.setStyleSheet("background=-color: white")
        if index.isValid():
            value = index.data(QtCore.Qt.ItemDataRole.DisplayRole)
            num = self.items.index(value)
            editor.setCurrentIndex(num)
        editor.blockSignals(False)

    def setModelData(self,
                     editor: QtWidgets.QWidget,
                     model: QtCore.QAbstractItemModel,
                     index: QtCore.QModelIndex
                    ) -> None:
        """ Use the data from the editor to set the model. """
        #print("ModeComboDelegate: setModelData")
        if index.isValid():
            model.setData(index, editor.currentText())

    def updateEditorGeometry(self,
                             editor: QtWidgets.QWidget,
                             option: QtWidgets.QStyleOptionViewItem,
                             _index: QtCore.QModelIndex
                            ) -> None:
        """ Update the geometry of the editor. """
        #print("ModeComboDelegate: updateEditorGeometry")
        editor.setGeometry(option.rect)

    @QtCore.pyqtSlot()
    def currentIndexChanged(self) -> None:
        """ Respond to change of current index. """
        #print("ModeComboDelegate: currentIndexChanged")
        self.commitData.emit(self.sender())
