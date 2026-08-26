import logging

from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.utils import timezone
from rest_framework.test import APITransactionTestCase

from qfieldcloud.core.middleware.timezone import TimezoneMiddleware
from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()
        self.factory = RequestFactory()

    def get_response(self, request):
        return None

    def test_activates_authenticated_users_saved_timezone(self):
        u1 = Person.objects.create(username="u1")
        u1.useraccount.timezone = "Europe/Sofia"
        u1.useraccount.save()

        request = self.factory.get("/")
        request.user = u1

        TimezoneMiddleware(self.get_response)(request)

        self.assertEqual(str(timezone.get_current_timezone()), "Europe/Sofia")

    def test_falls_back_to_server_timezone_for_anonymous_user(self):
        request = self.factory.get("/")
        request.user = AnonymousUser()

        TimezoneMiddleware(self.get_response)(request)

        self.assertEqual(
            str(timezone.get_current_timezone()), str(timezone.get_default_timezone())
        )
