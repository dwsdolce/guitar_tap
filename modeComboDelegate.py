from PyQt6 import QtWidgets, QtCore

class ModeComboDelegate(QtWidgets.QStyledItemDelegate):
    def __init__(self, parent, items) -> None:
        self.items = items
        super().__init__(parent)

    def createEditor(self, parent, option, index):
        #print("ModeComboDelegate: createEditor")
        self.editor = QtWidgets.QComboBox(parent)
        self.editor.setStyleSheet("background=-color: white; \n"
                                  "border: 1px solid gray; \n"
                                  "padding: 1px 3px 1px 3px;")
        self.editor.addItems(self.items)
        self.editor.currentIndexChanged.connect(self.currentIndexChanged)
        return self.editor
    
    def setEditorData(self, editor, index):
        #print("ModeComboDelegate: setEditorData")
        editor.blockSignals(True) # block signals that are not caused by the user
        editor.setStyleSheet("background=-color: white")
        if index.isValid():
            value = index.data(QtCore.Qt.ItemDataRole.DisplayRole)
            num = self.items.index(value)
            editor.setCurrentIndex(num)
        editor.blockSignals(False)

    def setModelData(self, editor, model, index):
        #print("ModeComboDelegate: setModelData")
        if index.isValid():
            model.setData(index, editor.currentText())
    
    def updateEditorGeometry(self, editor, option, index):
        #print("ModeComboDelegate: updateEditorGeometry")
        editor.setGeometry(option.rect)
    
    @QtCore.pyqtSlot()
    def currentIndexChanged(self):
        #print("ModeComboDelegate: currentIndexChanged")
        self.commitData.emit(self.sender())   
