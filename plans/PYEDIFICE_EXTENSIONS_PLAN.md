# Plan: pyedifice Extensions for guitar_tap

Provides a thin declarative layer over PySide6 for the 12 widgets not covered by
pyedifice's built-ins, plus moves the reactive state primitives (`ObservableObject`
and `Published`) out of `swiftui_compat` into the project itself.

All code goes into one new package:
`src/guitar_tap/views/pyedifice/`

Tests go into a new subdirectory:
`tests/pyedifice/`

Examples go into a new top-level directory:
`examples/pyedifice/`

No implementation now. This document defines *what* to build and *why*, to the
level of detail needed to start coding without further design decisions.

---

## 1. New Package Layout

```
src/guitar_tap/views/pyedifice/
├── __init__.py                  # re-exports everything below
├── observable.py                # ObservableObject + Published (moved from swiftui_compat)
├── double_spin_box.py           # DoubleSpinBox
├── list_widget.py               # ListWidget
├── tool_button.py               # ToolButton
├── menu.py                      # Menu
├── frame.py                     # Frame
├── plain_text_edit.py           # PlainTextEdit
├── text_browser.py              # TextBrowser
├── dialog.py                    # Dialog
├── dialog_button_box.py         # DialogButtonBox
├── graphics_view.py             # GraphicsView (wraps QGraphicsView + QGraphicsScene)
└── main_window.py               # MainWindow (conditional; see §2.12)

tests/pyedifice/
├── __init__.py
├── conftest.py                  # shared QApplication fixture
├── test_observable.py
├── test_double_spin_box.py
├── test_list_widget.py
├── test_tool_button.py
├── test_menu.py
├── test_frame.py
├── test_plain_text_edit.py
├── test_text_browser.py
├── test_dialog.py
├── test_dialog_button_box.py
└── test_graphics_view.py

examples/pyedifice/
├── README.md
├── example_observable.py
├── example_double_spin_box.py
├── example_list_widget.py
├── example_tool_button.py
├── example_menu.py
├── example_frame.py
├── example_plain_text_edit.py
├── example_text_browser.py
├── example_dialog.py
├── example_dialog_button_box.py
└── example_graphics_view.py
```

---

## 2. Widget Plans

Each widget section lists:
- **Wraps** — the PySide6 class
- **Props** — the declarative props to expose and their types
- **Signals wired** — Qt signals connected/disconnected via `diff_props`
- **`create_widget` notes** — any non-default constructor args
- **`update` notes** — any subtleties (signal blocking, order of ops, etc.)
- **Inherited for free** — props inherited from `QtWidgetElement` without any work
- **Test cases** — what to cover
- **Example** — what the example script demonstrates

---

### 2.1 `DoubleSpinBox` — `double_spin_box.py`

**Wraps:** `QtWidgets.QDoubleSpinBox`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `value` | `float` | `setValue` / `value()` |
| `minimum` | `float` | `setMinimum` |
| `maximum` | `float` | `setMaximum` |
| `single_step` | `float` | `setSingleStep` |
| `decimals` | `int` | `setDecimals` |
| `prefix` | `str` | `setPrefix` |
| `suffix` | `str` | `setSuffix` |
| `on_change` | `Callable[[float], None] \| None` | `valueChanged` signal |

**Signals wired:** `valueChanged(float)` — disconnect old, connect new in `update()`.
Block signals during `setValue` to avoid re-entrant callbacks.

**`create_widget` notes:** Plain `QDoubleSpinBox()`.

**`update` notes:** Always apply `minimum`/`maximum` before `value` to avoid
Qt clamping the value on the first render.

**Inherited for free:** `style`, `enabled`, `tool_tip`, `size_policy`.

**Test cases:**
- Initial render sets correct value, min, max, step, decimals, suffix, prefix.
- Changing `value` prop updates the widget without firing `on_change`.
- `on_change` fires when user changes value (simulate via `setValue` + `valueChanged`).
- Old `on_change` is disconnected when prop changes to a new callable.
- `on_change=None` does not crash.

**Example:** A panel with a labelled `DoubleSpinBox` controlling a displayed float
value that updates reactively.

---

### 2.2 `ListWidget` — `list_widget.py`

**Wraps:** `QtWidgets.QListWidget`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `items` | `list[str]` | full rebuild via `clear()` + `addItem()` |
| `current_row` | `int \| None` | `setCurrentRow` / `currentRow()` |
| `on_selection_change` | `Callable[[int, str \| None], None] \| None` | `currentRowChanged(int)` |
| `on_item_activated` | `Callable[[int, str], None] \| None` | `itemActivated` signal |
| `selection_mode` | `Qt.SelectionMode` | `setSelectionMode` |

**Signals wired:** `currentRowChanged` and `itemActivated`.

**`create_widget` notes:** Plain `QListWidget()`.

**`update` notes:** When `items` changes, call `blockSignals(True)`, `clear()`,
re-add all items, restore `current_row`, then `blockSignals(False)`. This avoids
spurious `on_selection_change` fires during the rebuild. Only rebuild if `items`
actually changed (check via `diff_props`).

**Inherited for free:** `style`, `enabled`, `tool_tip`, `size_policy`.

**Test cases:**
- Initial render populates the correct items.
- `current_row` prop selects the right row.
- Replacing `items` does not fire `on_selection_change`.
- `on_selection_change` fires with correct `(row, text)` after a programmatic
  selection change.
- `on_item_activated` fires with `(row, text)`.
- Empty `items` list does not crash.

**Example:** A list of measurement names; clicking one displays its details in a
`Label` beside it.

---

### 2.3 `ToolButton` — `tool_button.py`

**Wraps:** `QtWidgets.QToolButton`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `text` | `str` | `setText` |
| `icon` | `QIcon \| None` | `setIcon` |
| `tool_button_style` | `Qt.ToolButtonStyle` | `setToolButtonStyle` |
| `popup_mode` | `QToolButton.ToolButtonPopupMode \| None` | `setPopupMode` |
| `checkable` | `bool` | `setCheckable` |
| `checked` | `bool` | `setChecked` (with signal blocking) |
| `on_click` | `Callable[[], None] \| None` | `clicked` signal |
| `on_toggled` | `Callable[[bool], None] \| None` | `toggled` signal |

**Signals wired:** `clicked` and `toggled`.

**`create_widget` notes:** Plain `QToolButton()`.

**`update` notes:** Block signals when applying `checked` to avoid feedback.
Apply `checkable` before `checked`.

**Inherited for free:** `style`, `enabled`, `tool_tip`, `size_policy`.

**Test cases:**
- `text` and `icon` render correctly.
- `checkable=True` + `checked=True` sets the button state without firing `on_toggled`.
- `on_click` fires on click signal.
- `on_toggled` fires with correct bool.
- Old callbacks are disconnected on prop change.

**Example:** A toolbar row of `ToolButton` components with icons; one is a toggle
(checkable) that shows/hides a panel.

---

### 2.4 `Menu` — `menu.py`

**Wraps:** `QtWidgets.QMenu`

**Design note:** `QMenu` is not a layout-position widget — it is shown as a popup.
The wrapper manages the menu's declarative action list and attaches the menu to a
parent widget (typically a `ToolButton`) via `setMenu`. The component is rendered
as a zero-size invisible element; its underlying `QMenu` is passed to a parent
`ToolButton` or displayed on demand.

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `actions` | `list[MenuAction]` | full rebuild via `clear()` + `addAction()` |
| `title` | `str` | `setTitle` |

**`MenuAction` is a plain dataclass:**
```python
@dataclass
class MenuAction:
    text: str
    on_trigger: Callable[[], None] | None = None
    checkable: bool = False
    checked: bool = False
    enabled: bool = True
    separator_before: bool = False
```

**`create_widget` notes:** `QMenu()`.

**`update` notes:** On every `actions` change, `clear()` and rebuild. Reconnect
`triggered` slots for each action. Use `QAction.setData(i)` to identify which
action fired so a single slot can dispatch to the right `on_trigger`.

**Inherited for free:** `style`, `enabled`.

**Test cases:**
- Actions list populates the correct number of `QAction` items.
- `on_trigger` fires for the correct action.
- Checkable actions toggle `checked` state.
- Separator appears before marked actions.
- Empty `actions` list does not crash.

**Example:** A `ToolButton` whose `popup_mode` is `MenuButtonPopup`, with a `Menu`
child listing export format options.

---

### 2.5 `Frame` — `frame.py`

**Wraps:** `QtWidgets.QFrame`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `frame_shape` | `QFrame.Shape` | `setFrameShape` |
| `frame_shadow` | `QFrame.Shadow` | `setFrameShadow` |
| `line_width` | `int` | `setLineWidth` |

**`create_widget` notes:** `QFrame()`.

**`update` notes:** Straightforward; no signals.

**Inherited for free:** `style`, `enabled`, `size_policy`.

**Test cases:**
- `frame_shape` and `frame_shadow` are applied on creation.
- Changing props updates the widget.
- Default props produce a `StyledPanel` / `Raised` frame.

**Example:** A horizontal `HLine` separator between two sections of a settings panel.

---

### 2.6 `PlainTextEdit` — `plain_text_edit.py`

**Wraps:** `QtWidgets.QPlainTextEdit`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `plain_text` | `str` | `setPlainText` (only when changed) |
| `read_only` | `bool` | `setReadOnly` |
| `placeholder_text` | `str` | `setPlaceholderText` |
| `on_change` | `Callable[[str], None] \| None` | `textChanged` signal (converts to `toPlainText()`) |
| `maximum_block_count` | `int \| None` | `setMaximumBlockCount` (useful for log views) |

**`create_widget` notes:** `QPlainTextEdit()`.

**`update` notes:** Only call `setPlainText` when `plain_text` is in `diff_props`
to avoid resetting the cursor position on every render. Block signals during
`setPlainText`.

**Inherited for free:** `style`, `enabled`, `tool_tip`, `size_policy`.

**Test cases:**
- Initial text renders correctly.
- Changing `plain_text` prop updates the widget without firing `on_change`.
- `read_only=True` prevents editing.
- `on_change` fires with current text when user edits.
- `maximum_block_count` limits retained lines (log view use case).

**Example:** A live log view appending lines of analysis output.

---

### 2.7 `TextBrowser` — `text_browser.py`

**Wraps:** `QtWidgets.QTextBrowser`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `html` | `str` | `setHtml` |
| `open_external_links` | `bool` | `setOpenExternalLinks` |
| `on_anchor_clicked` | `Callable[[str], None] \| None` | `anchorClicked` signal (url → str) |

**`create_widget` notes:** `QTextBrowser()`.

**`update` notes:** Only call `setHtml` when `html` is in `diff_props`.

**Inherited for free:** `style`, `enabled`, `tool_tip`, `size_policy`.

**Test cases:**
- HTML content renders (check `toHtml()` is non-empty after `setHtml`).
- `on_anchor_clicked` fires with the URL string.
- `open_external_links=True` is applied.

**Example:** A help panel that renders the `help.html` file and opens doc links.

---

### 2.8 `Dialog` — `dialog.py`

**Wraps:** `QtWidgets.QDialog`

**Design note:** `QDialog` is a top-level window. The wrapper makes it declarative:
when the component is in the tree it is visible; when removed it is hidden. Children
are laid out inside a `QVBoxLayout` on the dialog.

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `title` | `str` | `setWindowTitle` |
| `modal` | `bool` | `setModal` |
| `on_accepted` | `Callable[[], None] \| None` | `accepted` signal |
| `on_rejected` | `Callable[[], None] \| None` | `rejected` signal |

**`create_widget` notes:** `QDialog()` with a `QVBoxLayout` installed. Show on
first render; call `hide()` / `show()` based on parent component mounting.

**`update` notes:** Update title and modal flag; reconnect accepted/rejected signals.

**Inherited for free:** `style`, `size_policy`.

**Test cases:**
- Dialog title is set correctly.
- `modal=True` sets the modal flag.
- `on_accepted` fires when `accept()` is called on the underlying widget.
- `on_rejected` fires when `reject()` is called.
- Old callbacks are disconnected on prop change.

**Example:** An "Edit Measurement" form inside a `Dialog` with an `on_accepted`
callback that commits the edit.

---

### 2.9 `DialogButtonBox` — `dialog_button_box.py`

**Wraps:** `QtWidgets.QDialogButtonBox`

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `standard_buttons` | `QDialogButtonBox.StandardButtons` | `setStandardButtons` |
| `on_accepted` | `Callable[[], None] \| None` | `accepted` signal |
| `on_rejected` | `Callable[[], None] \| None` | `rejected` signal |
| `orientation` | `Qt.Orientation` | constructor arg (horizontal default) |

**`create_widget` notes:** `QDialogButtonBox(orientation)`.

**`update` notes:** Reconnect `accepted`/`rejected` signals; update `standard_buttons`.

**Inherited for free:** `style`, `enabled`, `size_policy`.

**Test cases:**
- Correct buttons appear for `Ok | Cancel`.
- `on_accepted` fires when the OK button is clicked.
- `on_rejected` fires when Cancel is clicked.
- Changing `standard_buttons` prop rebuilds the button set.

**Example:** A `Dialog` containing a form and a `DialogButtonBox` at the bottom.

---

### 2.10 `GraphicsView` — `graphics_view.py`

**Wraps:** `QtWidgets.QGraphicsView` + `QtWidgets.QGraphicsScene` (paired together)

**Design note:** `QGraphicsView` and `QGraphicsScene` always appear together. The
wrapper owns both, exposes a `render_scene` callback (analogous to `PyQtPlot`'s
`plot_fun`) in which the caller imperatively constructs or updates scene items.
This is the right pattern: scene content is inherently imperative; the wrapper
provides the declarative container and lifecycle.

**Props:**

| Prop | Type | Maps to |
|------|------|---------|
| `render_scene` | `Callable[[QGraphicsScene], None]` | called in `update()` after `clear()` |
| `background_color` | `QColor \| None` | `scene.setBackgroundBrush` |
| `render_hint` | `QPainter.RenderHint \| None` | `view.setRenderHint` |
| `on_mouse_press` | `Callable[[QMouseEvent], None] \| None` | override `mousePressEvent` on subclass |
| `on_mouse_move` | `Callable[[QMouseEvent], None] \| None` | override `mouseMoveEvent` |

**`create_widget` notes:** Create a thin `QGraphicsView` subclass (defined privately
in the same file) that stores the event callbacks and calls them from overridden
event methods. Create a `QGraphicsScene`, install it on the view.

**`update` notes:** Call `scene.clear()` then `render_scene(scene)` whenever
`render_scene` is in `diff_props`. Apply background and render hints separately.

**Inherited for free:** `style`, `size_policy`, `on_resize`.

**Test cases:**
- `render_scene` is called on first render.
- `render_scene` is called again when the prop changes.
- `background_color` is applied to the scene.
- Mouse event callbacks fire when events are delivered to the view.

**Example:** A simple canvas that draws a frequency response curve using
`QGraphicsEllipseItem` and `QGraphicsLineItem` via `render_scene`.

---

### 2.11 `MainWindow` — `main_window.py`

**Wraps:** `QtWidgets.QMainWindow`

**Scope note:** `edifice.Window` covers the common case. This wrapper is only needed
if `guitar_tap` requires a menu bar, status bar, or dockable tool windows — none of
which `edifice.Window` provides. Write it only if that need materialises. The file
is listed in the plan to reserve the slot; it is the **lowest priority** item.

**Props (provisional):**

| Prop | Type | Maps to |
|------|------|---------|
| `title` | `str` | `setWindowTitle` |
| `status_message` | `str \| None` | `statusBar().showMessage` |
| `on_close` | `Callable[[], None] \| None` | `closeEvent` |

No tests or example planned until the need is confirmed.

---

## 3. Reactive State: `observable.py`

### What to move

Copy the following from `swiftui_compat` verbatim into
`src/guitar_tap/views/pyedifice/observable.py`:

| Symbol | Source file in swiftui_compat |
|--------|-------------------------------|
| `ObservableObject` | `swiftui_compat/observable.py` |
| `Published` | `swiftui_compat/descriptors.py` (the `Published` class only) |

The move is a copy-then-delete from the project's perspective — the original
`swiftui_compat` package is not modified. The two imports in `guitar_tap` that
currently read:

```python
from swiftui_compat import ObservableObject, Published
```

will be updated to:

```python
from guitar_tap.views.pyedifice import ObservableObject, Published
```

### What to leave in swiftui_compat

`ObservedObject`, `StateObject`, `EnvironmentObject`, `State`, `Binding`,
`BindingRef`, `View`, all layout containers, and everything else remain in
`swiftui_compat`. They are not used in `guitar_tap` and are not part of this plan.

### Adaptation notes

`Published.__get__` currently calls `notify_read` from a sibling `computed`
module inside swiftui_compat:

```python
try:
    from .computed import notify_read
    notify_read(obj, self._attr_name)
except ImportError:
    pass
```

Since `computed.py` will not be copied, this `try/except` block becomes dead code
but is harmless. Leave it in place on copy; it will silently no-op.

### Tests for `observable.py`

File: `tests/pyedifice/test_observable.py`

| Test | What it verifies |
|------|-----------------|
| `test_published_default` | `Published` returns its default before any set |
| `test_published_set_get` | Setting a `Published` field stores and returns the new value |
| `test_notify_fires_on_set` | `ObservableObject._notify_change` fires all subscribed callbacks |
| `test_subscribe_returns_unsubscribe` | Calling the returned unsubscribe callable stops notifications |
| `test_multiple_subscribers` | All subscribers are notified on change |
| `test_published_names_registry` | `__published_names__` is populated on the class |
| `test_dead_callback_cleaned_up` | A callback that raises is removed from the list |

### Example for `observable.py`

File: `examples/pyedifice/example_observable.py`

Demonstrates an `AudioEngine(ObservableObject)` with a `frequency = Published(440.0)`
field, wired to a `DoubleSpinBox` so that changing the spinbox updates the model and
a `Label` reflects the new value — without any explicit signal wiring in the view.

---

## 4. `__init__.py` Exports

`src/guitar_tap/views/pyedifice/__init__.py` re-exports the full public surface:

```python
from .observable import ObservableObject, Published
from .double_spin_box import DoubleSpinBox
from .list_widget import ListWidget
from .tool_button import ToolButton
from .menu import Menu, MenuAction
from .frame import Frame
from .plain_text_edit import PlainTextEdit
from .text_browser import TextBrowser
from .dialog import Dialog
from .dialog_button_box import DialogButtonBox
from .graphics_view import GraphicsView
```

`MainWindow` is not exported until implemented.

---

## 5. Test Infrastructure

### `tests/pyedifice/conftest.py`

All widget tests need a live `QApplication`. A shared `pytest` fixture creates one
per session:

```python
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="session")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app
```

Each widget test function accepts `qapp` as a parameter to ensure the application
exists before constructing any widgets.

### Test approach

Tests instantiate the `CustomWidget` subclass directly (not inside a full Edifice
render tree) by calling `create_widget()` and then `update(widget, diff_props)`
manually. This avoids needing a running Edifice engine for unit tests and keeps
tests fast.

---

## 6. Example Structure

Each example is a self-contained runnable script:

```python
import edifice as ed
from guitar_tap.views.pyedifice import <Widget>

@ed.component
def Main(self):
    # minimal reactive demo of the widget
    ...

if __name__ == "__main__":
    ed.App(Main()).start()
```

Examples are not imported by the main application — they exist solely as developer
documentation and manual smoke tests.

---

## 7. Implementation Order

| Priority | File | Reason |
|----------|------|--------|
| 1 | `observable.py` | Unblocks removal of `swiftui_compat` dependency |
| 2 | `double_spin_box.py` | Most heavily used control in guitar_tap UI |
| 3 | `list_widget.py` | Measurements list is central to the UI |
| 4 | `tool_button.py` | Used in several toolbars |
| 5 | `plain_text_edit.py` | Log/output panels |
| 6 | `frame.py` | Visual separators throughout |
| 7 | `dialog.py` | Edit/settings dialogs |
| 8 | `dialog_button_box.py` | Used inside dialogs |
| 9 | `menu.py` | Context menus on tool buttons |
| 10 | `text_browser.py` | Help view |
| 11 | `graphics_view.py` | Custom painting canvas |
| 12 | `main_window.py` | Only if dock/status-bar need is confirmed |

---

## 8. Out of Scope

- Modifying `swiftui_compat` source.
- Wrapping any PySide6 class not listed above.
- Changing the existing `guitar_tap` view files to use the new package
  (that is a subsequent migration step).
- Any `QGraphicsOpacityEffect` standalone wrapper — it is applied inside a
  `GraphicsView.update()` call, not as a separate component.
- Imperative calls (`QFileDialog`, `QInputDialog`, `QMessageBox`, `QSettings`)
  — these are used correctly as-is inside callbacks.
