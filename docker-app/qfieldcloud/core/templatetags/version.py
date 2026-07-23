from django import template
from django.conf import settings

register = template.Library()


@register.simple_tag
def get_qfieldcloud_version() -> str:
    """
    Get the QFieldCloud version
    """
    return settings.SENTRY_RELEASE
