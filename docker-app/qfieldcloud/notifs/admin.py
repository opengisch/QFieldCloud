from django.contrib import admin
from notifications.admin import NotificationAdmin as NotificationAdminBase
from notifications.models import Notification

admin.site.unregister(Notification)


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


admin.site.register(Notification, NotificationAdmin)
