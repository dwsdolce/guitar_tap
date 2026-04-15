# PySide6/Qt Widget Support in pyedifice

## Strategy

The goal is **not** to replace PySide6 widgets with pyedifice's built-in components
through composition. The goal is a **thin declarative wrapper** over the existing
PySide6 widgets already used in `guitar_tap`, using pyedifice's `CustomWidget` API.

`CustomWidget` is the public extension point. Subclassing it requires overriding
exactly two methods:

- `create_widget()` — instantiate and return the bare Qt widget (no parent; pyedifice
  handles parenting).
- `update(widget, diff_props)` — apply changed props to the already-live widget
  instance. `diff_props` is a `dict[str, tuple[old, new]]`.

The subclass inherits `style`, `size_policy`, `tool_tip`, `enabled`, and all standard
mouse/keyboard/resize/focus callbacks from `QtWidgetElement` at no extra cost.

```python
class MyWidget(ed.CustomWidget[QtWidgets.QFoo]):
    def __init__(self, value: int, on_change=None, **kwargs):
        super().__init__(**kwargs)
        self._register_props({"value": value, "on_change": on_change})

    def create_widget(self):
        return QtWidgets.QFoo()

    def update(self, widget, diff_props):
        match diff_props.get("value"):
            case (_, int(v)):
                widget.setValue(v)
        match diff_props.get("on_change"):
            case (old, new):
                if old: widget.valueChanged.disconnect(old)
                if new: widget.valueChanged.connect(new)
```

Widgets that are not visible UI elements (events, geometry types, I/O helpers,
enums) are marked as **utilities** — they need no wrapper and are used directly
from PySide6.

Widgets that pyedifice already wraps well enough that no `CustomWidget` is needed
are marked **already covered**.

---

## Key

| Symbol | Meaning |
|--------|---------|
| ✅ Already covered | pyedifice has a built-in component; no `CustomWidget` needed |
| 🔨 Needs CustomWidget | A visible widget with no built-in equivalent; wrap with `CustomWidget` |
| 🔧 Utility | Not a visible widget (event type, geometry, I/O, enum); use directly from PySide6 |
| 🔁 Imperative | A dialog/service that must be called imperatively; invoke inside a callback or `use_effect` |

---

## QtWidgets

| Qt Class | Status | Notes |
|----------|--------|-------|
| `QApplication` | 🔧 Utility | Managed by `edifice.App` |
| `QAbstractItemView` | 🔧 Utility | Abstract base class; never instantiated directly |
| `QCheckBox` | ✅ Already covered | `edifice.CheckBox` |
| `QComboBox` | ✅ Already covered | `edifice.Dropdown` |
| `QDialog` | 🔨 Needs CustomWidget | Wrap `QDialog` to give it declarative lifecycle; or use `edifice.Window` for modeless; or call imperatively |
| `QDialogButtonBox` | 🔨 Needs CustomWidget | Wrap with `CustomWidget`; standardised OK/Cancel button row |
| `QDoubleSpinBox` | 🔨 Needs CustomWidget | `edifice.SpinInput` wraps integer `QSpinBox` only; a `CustomWidget[QDoubleSpinBox]` is a one-page addition |
| `QFileDialog` | 🔁 Imperative | Static methods (`getOpenFileName`, etc.) belong in a button callback, not a widget tree |
| `QFormLayout` | ✅ Already covered | Use `edifice.GridView`; or lay out label/control pairs with `HBoxView` inside `VBoxView` |
| `QFrame` | 🔨 Needs CustomWidget | Thin `CustomWidget[QFrame]` gives the framed border; or use `VBoxView` with CSS border styling |
| `QGraphicsItem` | 🔨 Needs CustomWidget | Wrap the `QGraphicsView`/`QGraphicsScene` pair as a single `CustomWidget`; pyedifice has no graphics-scene support |
| `QGraphicsOpacityEffect` | 🔧 Utility | Applied to a widget imperatively inside `update()`; not a standalone widget |
| `QGridLayout` | ✅ Already covered | `edifice.GridView` |
| `QGroupBox` | ✅ Already covered | `edifice.GroupBoxView` |
| `QHBoxLayout` | ✅ Already covered | `edifice.HBoxView` |
| `QInputDialog` | 🔁 Imperative | Static convenience methods; call inside a button callback |
| `QLabel` | ✅ Already covered | `edifice.Label` |
| `QLineEdit` | ✅ Already covered | `edifice.TextInput` |
| `QListWidget` | 🔨 Needs CustomWidget | `CustomWidget[QListWidget]` is straightforward; propagates `currentItemChanged` and `itemActivated` signals |
| `QListWidgetItem` | 🔧 Utility | Data object passed to `QListWidget`; constructed inside `update()` |
| `QMainWindow` | ✅ Already covered | Use `edifice.Window`; `QMainWindow`-specific features (dockable panels, status bar) would need a `CustomWidget` |
| `QMenu` | 🔨 Needs CustomWidget | Wrap `QMenu` as a `CustomWidget` attached to a button; or build the menu imperatively inside an `on_click` callback |
| `QMessageBox` | 🔁 Imperative | Static methods (`information`, `warning`, `critical`, `question`); call inside a callback |
| `QPlainTextEdit` | 🔨 Needs CustomWidget | `edifice.TextInputMultiline` wraps `QTextEdit`; `QPlainTextEdit` has better performance for plain text and log-style output |
| `QProgressBar` | ✅ Already covered | `edifice.ProgressBar` |
| `QPushButton` | ✅ Already covered | `edifice.Button` / `edifice.ButtonView` |
| `QScrollArea` | ✅ Already covered | `edifice.VScrollView` / `HScrollView` / `FixScrollView` |
| `QSizePolicy` | 🔧 Utility | Passed as the `size_policy` prop inherited from `QtWidgetElement` |
| `QSlider` | ✅ Already covered | `edifice.Slider` |
| `QSpinBox` | ✅ Already covered | `edifice.SpinInput` |
| `QStackedWidget` | ✅ Already covered | `edifice.StackedView` |
| `QStyle` | 🔧 Utility | Qt internal styling enum/helper; not a visible widget |
| `QTextBrowser` | 🔨 Needs CustomWidget | Read-only rich-text/HTML viewer with navigation; `CustomWidget[QTextBrowser]` is a small wrapper |
| `QTextEdit` | ✅ Already covered | `edifice.TextInputMultiline` |
| `QToolButton` | 🔨 Needs CustomWidget | Supports icons and a popup menu arrow that `edifice.Button` does not; `CustomWidget[QToolButton]` is a small wrapper |
| `QVBoxLayout` | ✅ Already covered | `edifice.VBoxView` |
| `QWidget` | ✅ Already covered | `edifice.VBoxView` / `HBoxView` / `FixView` as generic containers |

---

## QtGui

All QtGui classes used in `guitar_tap` are utilities — values, event objects, or
painting helpers. None require a `CustomWidget`. They are used directly from PySide6,
typically as arguments to props or inside `update()` bodies.

| Qt Class | Status | Notes |
|----------|--------|-------|
| `QAction` | 🔧 Utility | Constructed imperatively inside a `QMenu`/`QToolButton` `update()` |
| `QBrush` | 🔧 Utility | Passed as a value to painting calls |
| `QCloseEvent` | 🔧 Utility | Event type; `Window(on_close=...)` handles it declaratively |
| `QColor` | 🔧 Utility | Passed as a value in style props and painting calls |
| `QContextMenuEvent` | 🔧 Utility | Event type; received by `on_mouse_*` callback or overridden in a custom widget |
| `QCursor` | 🔧 Utility | Passed as the `cursor` prop on any `QtWidgetElement` |
| `QFont` | 🔧 Utility | Passed as a value in style props or set via `widget.setFont()` in `update()` |
| `QFontMetrics` | 🔧 Utility | Measurement helper; used in layout calculations, not a widget |
| `QIcon` | 🔧 Utility | Passed as a prop value (e.g., to `Button` or a `CustomWidget[QToolButton]`) |
| `QImage` | 🔧 Utility | Used with `edifice.Image` / `NumpyImage`; also constructible inside `update()` |
| `QKeySequence` | 🔧 Utility | Passed as a value to `QAction` or shortcut props |
| `QMouseEvent` | 🔧 Utility | Event type; passed to `on_mouse_*` callbacks |
| `QPaintEvent` | 🔧 Utility | Event type; used inside `paintEvent()` overrides in custom widgets |
| `QPainter` | 🔧 Utility | Painting context; used inside `paintEvent()` in custom widgets |
| `QPalette` | 🔧 Utility | Theming helper; applied via `widget.setPalette()` in `update()` |
| `QPen` | 🔧 Utility | Passed as a value to painting calls |
| `QPixmap` | 🔧 Utility | Used with `edifice.Image`; also constructed inside `update()` |
| `QResizeEvent` | 🔧 Utility | Event type; passed to `on_resize` callback |
| `QWheelEvent` | 🔧 Utility | Event type; passed to `on_mouse_wheel` callback |

---

## QtCore

All QtCore classes used in `guitar_tap` are utilities. None require a `CustomWidget`.

| Qt Class | Status | Notes |
|----------|--------|-------|
| `QAbstractTableModel` | 🔧 Utility | Data model; constructed inside `update()` and passed to a view widget |
| `QBuffer` | 🔧 Utility | I/O helper; use directly |
| `QByteArray` | 🔧 Utility | Data container; use directly |
| `QEvent` | 🔧 Utility | Base event class; used in custom `event()` overrides |
| `QEventLoop` | 🔧 Utility | Managed by pyedifice's engine; do not create your own |
| `QIODevice` | 🔧 Utility | I/O base class; use directly |
| `QModelIndex` | 🔧 Utility | Passed by data-model signals; use directly |
| `QObject` | 🔧 Utility | Base class; used for signal/slot connections |
| `QPoint` | 🔧 Utility | Geometry value type |
| `QPointF` | 🔧 Utility | Geometry value type |
| `QSettings` | 🔧 Utility | Persistence; call directly — no declarative pattern needed |
| `QSignalBlocker` | 🔧 Utility | Used inside `update()` to prevent feedback loops when updating widget state |
| `QSize` | 🔧 Utility | Geometry value type |
| `QThread` | 🔧 Utility | Use `use_async_effect` hook instead where possible |
| `QTimer` | 🔧 Utility | Use `use_effect` / `use_async_effect` hooks instead where possible |
| `QVariant` | 🔧 Utility | Mostly transparent in Python |
| `Qt` | 🔧 Utility | Namespace of enums/constants; use directly |

---

## PyQtGraph

`edifice.extra.PyQtPlot` wraps `PlotWidget` and exposes it as a declarative component
via a `plot_fun` callback. All pyqtgraph plot items (`PlotDataItem`, `InfiniteLine`,
etc.) are constructed and updated imperatively inside that callback — which is exactly
the right pattern and needs no further wrapping.

| PyQtGraph Class | Status | Notes |
|-----------------|--------|-------|
| `PlotWidget` | ✅ Already covered | `edifice.extra.PyQtPlot` |
| `PlotDataItem` | 🔧 Utility | Constructed/updated inside `PyQtPlot`'s `plot_fun` callback |
| `ScatterPlotItem` | 🔧 Utility | Constructed/updated inside `PyQtPlot`'s `plot_fun` callback |
| `InfiniteLine` | 🔧 Utility | Constructed/updated inside `PyQtPlot`'s `plot_fun` callback |
| `TextItem` | 🔧 Utility | Constructed/updated inside `PyQtPlot`'s `plot_fun` callback |
| `mkBrush` | 🔧 Utility | Helper function; use directly |
| `mkColor` | 🔧 Utility | Helper function; use directly |
| `mkPen` | 🔧 Utility | Helper function; use directly |

---

## Summary

| Category | Total | ✅ Already covered | 🔨 Needs CustomWidget | 🔁 Imperative | 🔧 Utility |
|----------|-------|-------------------|----------------------|--------------|-----------|
| QtWidgets | 37 | 14 | 12 | 4 | 7 |
| QtGui | 19 | 0 | 0 | 0 | 19 |
| QtCore | 17 | 0 | 0 | 0 | 17 |
| PyQtGraph | 8 | 1 | 0 | 0 | 7 |
| **Total** | **81** | **15** | **12** | **4** | **50** |

### CustomWidget wrappers to write (12 widgets)

Listed roughly in order of how much of the `guitar_tap` UI depends on each:

1. **`QDoubleSpinBox`** — high-frequency control; straightforward single-prop wrapper
2. **`QListWidget`** — used for measurement lists; expose `currentItemChanged` and `itemActivated`
3. **`QToolButton`** — used for icon-bearing toolbar actions; expose `icon`, `text`, `on_click`, `popup_mode`
4. **`QMenu`** — context menus attached to tool buttons; expose a list of `QAction`-like dicts
5. **`QFrame`** — decorative separator/border; expose `frame_shape` and `frame_shadow` props
6. **`QPlainTextEdit`** — log/diagnostic output; expose `plain_text`, `read_only`, `on_change`
7. **`QTextBrowser`** — help/HTML content viewer; expose `html`, `source` (URL navigation)
8. **`QDialog`** — used for settings and edit dialogs; expose `title`, `modal`, `on_accept`, `on_reject`
9. **`QDialogButtonBox`** — standard OK/Cancel/Apply row used inside dialogs
10. **`QGraphicsItem`** / graphics scene — custom painting canvas; wrap `QGraphicsView` + `QGraphicsScene` together as a single `CustomWidget`
11. **`QGraphicsOpacityEffect`** — applied inside an existing `CustomWidget`'s `update()`; not a standalone widget
12. **`QMainWindow`** — only needed if dock panels or status bar are required; otherwise `edifice.Window` is sufficient

### Imperative calls (4 items, no wrapper needed)

- **`QFileDialog`** — `QFileDialog.getOpenFileName(...)` inside a button `on_click` callback
- **`QInputDialog`** — `QInputDialog.getText(...)` / `getDouble(...)` inside a callback
- **`QMessageBox`** — `QMessageBox.question(...)` / `warning(...)` inside a callback
- **`QSettings`** — read/write at startup and shutdown; not part of the widget tree

### Notes on swiftui_compat

`guitar_tap` uses only `ObservableObject` and `Published` from `swiftui_compat`.
These are pure Python reactive-programming helpers with no Qt widget footprint.
They have no bearing on the `CustomWidget` plan above.
