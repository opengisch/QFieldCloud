"""Mark datetimes with `data-qfc-datetime-tooltip`, so hovering over them shows a tooltip.

The visible text stays whatever the server renders, the tooltip in `staticfiles/js/datetime_tooltip.js`
shows the same moment in other forms (relative, user's timezone, browser's timezone, UTC).
"""

import datetime
import importlib
from collections.abc import Callable
from typing import Any

from django.utils import formats, timezone
from django.utils.html import format_html
from django_tables2.columns import DateTimeColumn, library

# Modules that import Django's or Unfold's `display_for_field` / `display_for_value` by name.
ADMIN_DISPLAY_MODULES = (
    "django.contrib.admin.utils",
    "django.contrib.admin.helpers",
    "django.contrib.admin.templatetags.admin_list",
    "unfold.utils",
    "unfold.fields",
    "unfold.sections",
    "unfold.templatetags.unfold_list",
)


def datetime_tooltip_attrs(value: Any) -> str:
    """Return the attributes turning an element into a tooltip anchor for a time zone aware datetime.

    Used in templates as `<span {{ project.created_at|datetime_tooltip_attrs }}>...</span>`.
    """
    if not isinstance(value, datetime.datetime) or timezone.is_naive(value):
        return ""

    return format_html(
        'data-qfc-datetime-tooltip="{}" data-tz="{}"',
        value.isoformat(),
        # the full timezone name, `get_current_timezone_name()` may return an abbreviation instead
        str(timezone.get_current_timezone()),
    )


def datetime_tooltip_html(value: datetime.datetime, text: Any) -> Any:
    """Wrap `text` in a `<time>` tooltip anchor for `value`, naive datetimes keep the plain text."""
    attrs = datetime_tooltip_attrs(value)

    if not attrs:
        return text

    return format_html("<time {}>{}</time>", attrs, text)


@library.register
class DateTimeTooltipColumn(DateTimeColumn):
    """django-tables2 column for datetimes, it wrapps `DateTimeColumn` text in a tooltip anchor."""

    def render(
        self, record: Any, table: Any, value: Any, bound_column: Any, **kwargs: Any
    ) -> Any:
        text = super().render(record, table, value, bound_column, **kwargs)

        return datetime_tooltip_html(value, text)


def _wrap_display(original: Callable[..., Any]) -> Callable[..., Any]:
    """Wrap `display_for_field` or `display_for_value`, both take the displayed value first."""

    def display(value: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(value, datetime.datetime):
            # the same text the admin shows for datetimes
            local_value = value

            if timezone.is_aware(value):
                local_value = timezone.localtime(value)

            return datetime_tooltip_html(value, formats.localize(local_value))

        return original(value, *args, **kwargs)

    return display


def patch_admin_datetime_display() -> None:
    """Make every datetime shown by the admin a tooltip anchor."""
    for module_name in ADMIN_DISPLAY_MODULES:
        module = importlib.import_module(module_name)

        for function_name in ("display_for_field", "display_for_value"):
            if hasattr(module, function_name):
                setattr(
                    module, function_name, _wrap_display(getattr(module, function_name))
                )
