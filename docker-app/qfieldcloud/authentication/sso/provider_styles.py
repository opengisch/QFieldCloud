from copy import deepcopy

from django.conf import settings
from django.http import HttpRequest
from django.templatetags.static import static


class SSOProviderStyles:
    """Helper class to get the style settings for a provider."""

    def __init__(self, request: HttpRequest):
        self.request = request

    def get(self, provider_id: str) -> dict:
        """Get the style settings for a (sub)provider."""
        style_settings = settings.QFIELDCLOUD_SSO_PROVIDER_STYLES.get(provider_id, {})
        styles = deepcopy(style_settings)

        for theme_id, theme in styles.items():
            if not isinstance(theme, dict):
                continue

            logo = theme.get("logo")
            if logo and not logo.startswith("http"):
                # Assume a relative path - create an absolute URL
                theme["logo"] = self.request.build_absolute_uri(static(logo))

        return styles
