from datetime import timedelta

from django.core.management import call_command
from django.db import close_old_connections
from django.test import TestCase
from django.utils import timezone
from django_cron.management.commands import runcrons
from django_currentuser.middleware import _set_current_user
from notifications.models import Notification
from notifications.signals import notify

from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    Team,
    UserAccount,
)
from qfieldcloud.core.tests.utils import set_subscription, setup_subscription_plans


class QfcTestCase(TestCase):
    """
    This tests that the notifications are sent
    """

    @classmethod
    def setUpClass(cls):
        # remove this once https://github.com/Tivix/django-cron/pull/176 is merged
        cls._close_old_connections = close_old_connections

        def noop():
            pass

        runcrons.close_old_connections = noop

    @classmethod
    def tearDownClass(cls):
        # restore above monkeypatch
        runcrons.close_old_connections = cls._close_old_connections

    def assertNotifs(self, expected_count, filter=None):
        if filter is None:
            filter = {}

        notifications = Notification.objects.filter(**filter)
        actual_count = notifications.count()
        if actual_count != expected_count:
            details = "\n".join(f"- {n}" for n in notifications)
            raise AssertionError(
                f"Expected {expected_count}, but got {actual_count} for {filter}\nDetails:\n{details}"
            )

    def setUp(self):
        setup_subscription_plans()

        # Without current user, no notifications are sent
        # (one day, maybe we could create them as AnonymousUser, see https://github.com/django-notifications/django-notifications/issues/13)
        _set_current_user(None)

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.user2 = Person.objects.create_user(username="user2", password="abc123")
        self.user3 = Person.objects.create_user(username="user3", password="abc123")
        self.otheruser = Person.objects.create_user(
            username="otheruser", password="abc123"
        )

    def test_no_self_notifications(self):
        # No notification to the actor of the action
        # (at some point, we could create the notif but set it as read)
        _set_current_user(self.user1)
        Organization.objects.create(username="org2", organization_owner=self.user1)
        self.assertNotifs(0, {"recipient": self.user1})

    def test_organization(self):
        _set_current_user(self.otheruser)

        # Org owner is notified of creation
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        self.assertNotifs(1, {"recipient": self.user1})

        # Org owner is notified of deletion
        org1.delete()
        self.assertNotifs(2, {"recipient": self.user1})

    def test_organization_members(self):
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )

        _set_current_user(self.otheruser)

        # Set user2, user3 as member of organization1
        OrganizationMember.objects.create(
            organization=org1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
        )
        memb2 = OrganizationMember.objects.create(
            organization=org1,
            member=self.user3,
            role=OrganizationMember.Roles.MEMBER,
        )
        self.assertNotifs(2, {"recipient": self.user1})
        self.assertNotifs(2, {"recipient": self.user2})
        self.assertNotifs(1, {"recipient": self.user3})

        memb2.delete()
        self.assertNotifs(3, {"recipient": self.user1})
        self.assertNotifs(3, {"recipient": self.user2})
        self.assertNotifs(2, {"recipient": self.user3})

        org1.delete()
        self.assertNotifs(5, {"recipient": self.user1})
        self.assertNotifs(5, {"recipient": self.user2})
        self.assertNotifs(2, {"recipient": self.user3})

    def test_team_members(self):
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        memb2 = org1.members.create(member=self.user2)
        org1.members.create(member=self.user3)
        t1 = org1.teams.create(username="t1")

        _set_current_user(self.otheruser)

        # Set user2, user3 as members of team1
        t1.members.create(member=self.user2)
        t1.members.create(member=self.user3)

        self.assertNotifs(2, {"recipient": self.user1})
        self.assertNotifs(2, {"recipient": self.user2})
        self.assertNotifs(1, {"recipient": self.user3})

        memb2.delete()
        self.assertNotifs(4, {"recipient": self.user1})
        self.assertNotifs(4, {"recipient": self.user2})
        self.assertNotifs(3, {"recipient": self.user3})

        t1.delete()
        self.assertNotifs(6, {"recipient": self.user1})
        self.assertNotifs(4, {"recipient": self.user2})
        self.assertNotifs(5, {"recipient": self.user3})

    def test_projects(self):
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        # Activate Subscription
        set_subscription(org1, "default_org")
        org1.members.create(member=self.user2)
        t1 = Team.objects.create(username="t1", team_organization=org1)
        t1.members.create(member=self.user2)

        _set_current_user(self.otheruser)

        # create a project
        p1 = Project.objects.create(name="p1", owner=org1, is_public=True)
        self.assertNotifs(1, {"recipient": self.user1})
        self.assertNotifs(0, {"recipient": self.user2})
        self.assertNotifs(0, {"recipient": self.user3})

        # add a collaborator (team)
        p1.collaborators.create(collaborator=t1)
        self.assertNotifs(2, {"recipient": self.user1})
        self.assertNotifs(1, {"recipient": self.user2})
        self.assertNotifs(0, {"recipient": self.user3})

        # add a collaborator (user)
        org1.members.create(member=self.user3)
        p1.collaborators.create(collaborator=self.user3)
        self.assertNotifs(4, {"recipient": self.user1})
        self.assertNotifs(3, {"recipient": self.user2})
        self.assertNotifs(2, {"recipient": self.user3})

    def test_cron(self):
        # Ensuring cron works

        user1 = self.user1
        user1.email = "test@example.com"
        user1.save()

        old = timezone.now() - timedelta(minutes=65)
        now = timezone.now()

        notify.send(
            user1,
            verb="tests_old",
            action_object=user1,
            recipient=[user1],
            timestamp=old,
        )
        notify.send(
            user1,
            verb="tests_now",
            action_object=user1,
            recipient=[user1],
            timestamp=now,
        )

        # When disabled, no cron job sends notifications
        user1.useraccount.notifs_frequency = UserAccount.NOTIFS_DISABLED
        user1.useraccount.save()
        self.assertNotifs(2, {"emailed": False})
        self.assertNotifs(0, {"emailed": True})
        call_command("runcrons", "--force")
        self.assertNotifs(2, {"emailed": False})
        self.assertNotifs(0, {"emailed": True})

        # When daily, we still don't send, as notification isn't old enough
        user1.useraccount.notifs_frequency = UserAccount.NOTIFS_DAILY
        user1.useraccount.save()
        self.assertNotifs(2, {"emailed": False})
        self.assertNotifs(0, {"emailed": True})
        call_command("runcrons", "--force")
        self.assertNotifs(2, {"emailed": False})
        self.assertNotifs(0, {"emailed": True})

        # When hourly, we send all notifs, since we have one that is old enough
        user1.useraccount.notifs_frequency = UserAccount.NOTIFS_HOURLY
        user1.useraccount.save()
        self.assertNotifs(2, {"emailed": False})
        self.assertNotifs(0, {"emailed": True})
        call_command("runcrons", "--force")
        self.assertNotifs(0, {"emailed": False})
        self.assertNotifs(2, {"emailed": True})
