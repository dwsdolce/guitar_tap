"""
Utility views and helpers — mirrors Swift Views/Utilities/.
"""
from .tap_settings_view import AppSettings
from .gt_images import GtImages

__all__ = [
    "AppSettings",
    "GtImages",
]

# NamedMutex is Windows-only; it lives at the project root (named_mutex.py)
#   and is imported only from guitar_tap.py.
# MacAccess is macOS-only; import it directly when needed:
#   from views.utilities.platform_adapters import MacAccess
