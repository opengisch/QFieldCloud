import logging

from django.conf import settings
from django.core.mail import send_mail
from django.db.models import Exists
from django.db.models.expressions import OuterRef
from django.db.models.functions import Now
from django.template.loader import render_to_string
from django_cron import CronJobBase, Schedule
from notifications.models import Notification

from qfieldcloud.core.models import User


class SendNotificationsJob(CronJobBase):
    schedule = Schedule(run_every_mins=1)
    code = "qfieldcloud.send_notifications"

    # TODO : not sure if/how this is logged somewhere
    def do(self):
        try:
            users = User.objects.filter(type=User.Type.PERSON).filter(
                Exists(
                    Notification.objects.filter(
                        unread=True,
                        emailed=False,
                        timestamp__lte=Now()
                        - OuterRef("useraccount__notifs_frequency"),
                    )
                )
            )
            for user in users:
                logging.debug(f"Retrieving notifications for {user}")

                notifs = Notification.objects.filter(
                    recipient=user, unread=True, emailed=False
                )
                if not notifs:
                    logging.debug(f"{user} has no notifications.")
                    continue

                if not user.email:
                    logging.warning(f"{user} has notifications, but no email set !")
                    continue

                QFIELDCLOUD_HOST = settings.QFIELDCLOUD_HOST

                logging.debug(f"Sending an email to {user} !")

                context = {
                    "notifs": notifs,
                    "username": user.username,
                    "hostname": QFIELDCLOUD_HOST,
                }

                subject = render_to_string(
                    "notifs/notification_email_subject.txt", context
                )
                body_html = render_to_string(
                    "notifs/notification_email_body.html", context
                )
                body_plain = render_to_string(
                    "notifs/notification_email_body.txt", context
                )

                # TODO : use mass_send_mail
                send_mail(
                    subject.strip(),
                    body_plain,
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    html_message=body_html,
                )

                notifs.update(emailed=True)

        except Exception as e:
            logging.exception(e)
            raise e
