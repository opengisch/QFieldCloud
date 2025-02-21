from django import template
from django.utils import formats
from django.utils.html import avoid_wrapping
from django.utils.translation import gettext as _
from django.utils.translation import ngettext

register = template.Library()


@register.filter(is_safe=True)
def filesizeformat10(bytes_) -> str:
    """
    Format the value like a 'human-readable' file size (i.e. 13 KB, 4.1 MB,
    102 bytes, etc.).

    Unlike Django's `filesizeformat` which uses powers of 2 (e.g. 1024KB==1MB), `filesizeformat10` uses powers of 10 (e.g. 1000KB==1MB)
    """
    try:
        bytes_ = int(bytes_)
    except (TypeError, ValueError, UnicodeDecodeError):
        value = ngettext("%(size)d byte", "%(size)d bytes", 0) % {"size": 0}
        return avoid_wrapping(value)

    def filesize_number_format(value):
        return formats.number_format(round(value, 1), 1)

    KB = 10**3
    MB = 10**6
    GB = 10**9
    TB = 10**12
    PB = 10**15

    negative = bytes_ < 0
    if negative:
        bytes_ = -bytes_  # Allow formatting of negative numbers.

    if bytes_ < KB:
        value = ngettext("%(size)d byte", "%(size)d bytes", bytes_) % {"size": bytes_}
    elif bytes_ < MB:
        value = _("%s KB") % filesize_number_format(bytes_ / KB)
    elif bytes_ < GB:
        value = _("%s MB") % filesize_number_format(bytes_ / MB)
    elif bytes_ < TB:
        value = _("%s GB") % filesize_number_format(bytes_ / GB)
    elif bytes_ < PB:
        value = _("%s TB") % filesize_number_format(bytes_ / TB)
    else:
        value = _("%s PB") % filesize_number_format(bytes_ / PB)

    if negative:
        value = "-%s" % value

    return avoid_wrapping(value)
