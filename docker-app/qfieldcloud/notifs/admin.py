from notifications.admin import NotificationAdmin as NotificationAdminBase
from notifications.models import Notification

from qfieldcloud.core.admin import qfc_admin_site


class NotificationAdmin(NotificationAdminBase):
    list_display = (
        "actor",
        "verb",
        "action_object",
        "target",
        "timestamp",
        "recipient",
        "unread",
    )

    list_select_related = ("recipient",)

    list_per_page = 10

    search_fields = ("recipient__username__icontains",)


qfc_admin_site.register(Notification, NotificationAdmin)
