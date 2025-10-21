"""
    Create a toolbar with modifications for the layout and modify
    the help button. The modifications the toolbar layout remove
    unused tools and adds a help button.
"""

import re
from PyQt6 import QtWidgets
from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
from matplotlib import pyplot as plt
import fft_canvas as fft_c


class FftToolbar(NavigationToolbar):
    """Overload the Navigation Toolbar class so that the home button behavior
    is modified to set the ylimits to -100. This takes care of any pan or
    zoom that was done before the home button was pressed.
    """

    extended_toolitems: str = ""

    def __init__(self, canvas: fft_c.FftCanvas, parent: QtWidgets.QWidget) -> None:

        # Add the Help tool
        self.toolitems.insert(
            # Add 'customize' action after 'subplots'
            [name for name, *_ in self.toolitems].index("Save") + 1,
            (
                "Help",
                "List information on support for navigation bar",
                "help",
                "display_help",
            ),
        )

        # Remove two of the tools since they are confusing
        self.extended_toolitems = [
            item
            for item in self.toolitems
            if item[0] != "Customize" and item[0] != "Subplots"
        ]
        self.toolitems = self.extended_toolitems.copy()

        # Add in the grid and grid_minor keybindings since they are helpful.
        self.extended_toolitems = [
            item
            for item in self.extended_toolitems
            if item[0] is not None and item[0] != "Help"
        ]
        self.extended_toolitems.append(("grid", "Toggle major grids", "", ""))
        self.extended_toolitems.append(
            ("grid_minor", "Toggle major and minor grids", "", "")
        )
        self.extended_toolitems.sort(key=lambda x: x[0])
        super().__init__(canvas, parent)

    def format_shortcut(self, key_sequence: str) -> str:
        """
        Convert a shortcut string from the notation used in rc config to the
        standard notation for displaying shortcuts, e.g. 'ctrl+a' -> 'Ctrl+A'.
        """
        return (
            key_sequence
            if len(key_sequence) == 1
            else re.sub(r"\+[A-Z]", r"+Shift\g<0>", key_sequence).title()
        )

    def _format_tool_keymap(self, name: str) -> str:
        """Find the keymap from the rc file and return."""
        # print(f"_format_tool_keymap: {name}")
        keymap = f"keymap.{name}"
        if keymap in plt.rcParams:
            keys = plt.rcParams[keymap]
        else:
            keys = ""
        return ", ".join(self.format_shortcut(key) for key in keys)

    def _get_help_entries(self) -> list[str]:
        """Format the help for a single command."""
        return [
            (name, self._format_tool_keymap(name.lower()), description)
            for name, description, _, _ in self.extended_toolitems
            if name
        ]

    def _get_help_html(self) -> str:
        """Format the table containing the help."""
        fmt = "<tr><td>{}</td><td>{}</td><td>{}</td></tr>"
        rows = [fmt.format("<b>Action</b>", "<b>Shortcuts</b>", "<b>Description</b>")]
        rows += [fmt.format(*row) for row in self._get_help_entries()]
        return (
            "<style>td {padding: 0px 4px}</style>"
            "<table><thead>" + rows[0] + "</thead>"
            "<tbody>".join(rows[1:]) + "</tbody></table>"
        )

    def display_help(self) -> None:
        """Use a message box to display the HTML help."""
        QtWidgets.QMessageBox.information(None, "Help", self._get_help_html())

    def home(self, *args) -> None:
        """Make sure the current y axes limits are used for the home button"""
        self.canvas.fft_axes.set_ylim(-100, 0)
        super().home()
