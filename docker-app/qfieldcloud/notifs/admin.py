from notifications.admin import NotificationAdmin

# Override django-notification's list display
NotificationAdmin.list_display = (
    "actor",
    "verb",
    "action_object",
    "target",
    "timestamp",
    "recipient",
    "unread",
)
