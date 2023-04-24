"""
    Custom editor for the mode column
"""
from PyQt6 import QtWidgets, QtCore
import gt_images as gt_i

class ShowComboDelegate(QtWidgets.QStyledItemDelegate):
    """ Provides a combobox for selecting mode values. """

    enable:bool = True

    # pylint: disable=invalid-name
    def createEditor(self,
                     parent: QtWidgets.QWidget,
                     _option: QtWidgets.QStyleOptionViewItem,
                     _index: QtCore.QModelIndex
                    ) -> QtWidgets.QWidget:
        """ Create the editor for the mode column. """
        #print("ShowComboDelegate: createEditor")
        # pylint: disable=attribute-defined-outside-init
        self.editor = QtWidgets.QToolButton(parent)
        self.editor.setStyleSheet("background=-color: red; \n"
                                  "border: 1px solid blue; \n"
                                  "padding: 1px 1px 1px 1px;")
        self.editor.setIcon(gt_i.GtImages.red_icon())
        self.editor.setIconSize(QtCore.QSize(21, 21))
        self.editor.setStyleSheet('border: none')
        self.editor.setCheckable(True)
        self.editor.setChecked(False)

        self.editor.toggled.connect(self.button_toggled)
        self.editor.setFocusPolicy(QtCore.Qt.FocusPolicy.NoFocus)
        return self.editor

    def setEditorData(self, editor: QtWidgets.QToolButton, index: QtCore.QModelIndex) -> None:
        """ Set the data in the editor from the model data. """
        #print("ShowComboDelegate: setEditorData")
        editor.blockSignals(True) # block signals that are not caused by the user
        editor.setStyleSheet("background=-color: white")

        if index.isValid():
            print(f"setEditorData: row = {index.row()}, col = {index.column()}")
            value = index.model().data_value(index)
            #print(f"setEditorData: value: {value}")
            if value == "on":
                editor.setChecked(True)
                editor.setIcon(gt_i.GtImages.green_icon())
            else:
                editor.setChecked(False)
                editor.setIcon(gt_i.GtImages.red_icon())
        editor.blockSignals(False)

    def setModelData(self,
                     editor: QtWidgets.QToolButton,
                     model: QtCore.QAbstractItemModel,
                     index: QtCore.QModelIndex
                    ) -> None:
        """ Use the data from the editor to set the model. """
        #print("ShowComboDelegate: setModelData")
        if index.isValid():
            if editor.isChecked():
                #print(f"setModelData: value: checked")
                model.setData(index, "on")
                editor.setIcon(gt_i.GtImages.green_icon())
            else:
                #print(f"setModelData: value: unchecked")
                model.setData(index, 'off')
                editor.setIcon(gt_i.GtImages.red_icon())

    def updateEditorGeometry(self,
                             editor: QtWidgets.QWidget,
                             option: QtWidgets.QStyleOptionViewItem,
                             _index: QtCore.QModelIndex
                            ) -> None:
        """ Update the geometry of the editor. """
        #print("ShowComboDelegate: updateEditorGeometry")
        editor.setGeometry(option.rect)

    def eventFilter(self, obj: QtWidgets.QToolButton, event: QtCore.QEvent) -> bool:
        """ Enable editor is there are any events on the item. """
        #print(f"ShowComboDelegate: eventFilter: enable: {self.enable}")
        #print(f"showComboDelegate: eventFilter: {event.type().name}")

        obj.setEnabled(self.enable)
        return super().eventFilter(obj, event)

    def button_toggled(self, _checked: bool) -> None:
        """ Respond to toggle of button. """
        self.commitData.emit(self.sender())
