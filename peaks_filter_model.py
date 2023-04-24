"""
    Filter for filter proxy to sort columns based on column data type.
"""
from PyQt6 import QtCore
from peaks_model import ColumnIndex

# pylint: disable=too-few-public-methods
class PeaksFilterModel(QtCore.QSortFilterProxyModel):
    """ Add a custom filter to handle the sorting of the columns. This is required
        due to the value displayed in the table being a string but we want to sort
        on the original numeric data or, for the case of cents on the absolute
        value of the cents.
    """

    # pylint: disable=invalid-name
    def lessThan(self, left: QtCore.QModelIndex, right: QtCore.QModelIndex):
        """ Calculate per the class description. """
        match left.column():
            case ColumnIndex.Show.value:
                left_show: str = self.sourceModel().show_value(left)
                right_show: str = self.sourceModel().show_value(right)
                match left_show:
                    case 'on':
                        match right_show:
                            case 'on':
                                less_than = False
                            case 'off':
                                less_than = False
                    case 'off':
                        match right_show:
                            case 'on':
                                less_than = True
                            case 'off':
                                less_than = False
                    case _:
                        less_than = False
            case ColumnIndex.Freq.value | ColumnIndex.Mag.value:
                # Sort by numeric value (assumes left and right column are the same)
                # Use the python value instead of the numpy value so that a bool is
                # returned instead of a numpy.bool_.
                less_than = (self.sourceModel().data_value(left) <
                             self.sourceModel().data_value(right))
                less_than = less_than.item()
            case ColumnIndex.Pitch.value:
                # Use the freq to define order
                # Use the python value instead of the numpy value so that a bool is
                # returned instead of a numpy.bool_.
                left_freq = self.sourceModel().freq_value(left)
                right_freq  = self.sourceModel().freq_value(right)
                less_than = left_freq < right_freq
                less_than = less_than.item()
            case ColumnIndex.Cents.value:
                # Sort by absolute value of cents (so +/-3 is less than +/- 4)
                left_cents = self.sourceModel().pitch.cents(self.sourceModel().freq_value(left))
                right_cents = self.sourceModel().pitch.cents(self.sourceModel().freq_value(right))
                less_than = abs(left_cents) < abs(right_cents)
            case ColumnIndex.Modes.value:
                left_mode = self.sourceModel().mode_value(left)
                right_mode = self.sourceModel().mode_value(right)
                less_than = left_mode < right_mode
            case _:
                less_than = True
        return less_than
    
    def data_value(self, index: QtCore.QModelIndex) -> QtCore.QVariant:
        # Translate filter model index to model index.

        return self.sourceModel().data_value(self.mapToSource(index))
