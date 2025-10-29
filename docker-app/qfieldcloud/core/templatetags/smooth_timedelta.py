from django import template
from django.utils.translation import gettext as _

register = template.Library()


@register.filter()
def smooth_timedelta(timedeltaobj):
    """Convert a datetime.timedelta object into Days, Hours, Minutes, Seconds.
    Inspired by: https://stackoverflow.com/a/46928226/1226137
    """
    secs = timedeltaobj.total_seconds()
    time_str = ""
    if secs > 86400:  # 60sec * 60min * 24hrs
        days = secs // 86400
        time_str += _("{} days").format(int(days))
        secs = secs - days * 86400

    if secs > 3600:
        hrs = secs // 3600
        time_str += _(" {} hours").format(int(hrs))
        secs = secs - hrs * 3600

    if secs > 60:
        mins = secs // 60
        time_str += _(" {} minutes").format(int(mins))
        secs = secs - mins * 60

    if secs > 0:
        time_str += _(" {} seconds").format(int(secs))

    return time_str
