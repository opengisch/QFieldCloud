import copy
from typing import Any

from django.conf import settings
from django.http import HttpRequest
from django.utils.translation import gettext as _

# Default whitelabel configuration
DEFAULT_WHITELABEL = {
    # Branding
    "site_title": _("QFieldCloud"),
    # Logos (paths relative to static directory)
    "logo_navbar": "logo_sidetext_white.svg",
    "logo_main": "logo_undertext.svg",
    "favicon": "favicon.ico",
}


def get_whitelabel_settings() -> dict[str, Any]:
    """
    Get whitelabel settings by merging user settings with defaults.
    Filters out None values from user settings to preserve defaults.
    """
    # Start with a deep copy of defaults
    whitelabel_settings = copy.deepcopy(DEFAULT_WHITELABEL)

    user_settings = {}
    for k, v in getattr(settings, "WHITELABEL", {}).items():
        if v is None:
            continue

        user_settings[k] = v

    # Update defaults with user settings
    whitelabel_settings.update(user_settings)

    # Post-processing: Add any computed defaults or normalization here
    # Example: favicon could default to logo_navbar if not set
    # whitelabel_settings["favicon"] = whitelabel_settings["favicon"] or "default.ico"

    return whitelabel_settings


def whitelabel(request: HttpRequest) -> dict[str, Any]:
    """Make whitelabel configuration available to all templates with translations."""

    whitelabel_config = get_whitelabel_settings()

    return {
        "whitelabel": whitelabel_config,
    }
