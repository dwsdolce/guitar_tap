"""
Utility views and helpers — mirrors Swift Views/Utilities/.
"""
from .tap_settings_view import AppSettings
from .gt_images import GtImages
from .tap_display_settings import (
    show_unknown_modes,
    set_show_unknown_modes,
    default_freq_range,
    saved_freq_range,
    saved_db_range,
)

__all__ = [
    "AppSettings",
    "GtImages",
    "show_unknown_modes",
    "set_show_unknown_modes",
    "default_freq_range",
    "saved_freq_range",
    "saved_db_range",
]

# NamedMutex is Windows-only; import it directly when needed:
#   from views.utilities.named_mutex import NamedMutex
# MacAccess is macOS-only; import it directly when needed:
#   from views.utilities.platform_adapters import MacAccess
