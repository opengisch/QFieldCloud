import logging

from django.db import IntegrityError
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    User,
    UserAccount,
)

from .utils import set_subscription, setup_subscription_plans

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(
            username="user1", password="abc123", email="user1@example.com"
        )
        self.token1 = AuthToken.objects.get_or_create(
            user=self.user1,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        # Create a second user
        self.user2 = Person.objects.create_user(
            username="user2", password="abc123", email="user2@example.com"
        )
        self.token2 = AuthToken.objects.get_or_create(
            user=self.user2,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        # Create a second user
        self.user3 = Person.objects.create_user(
            username="user3", password="abc123", email="user3@example.com"
        )
        self.token3 = AuthToken.objects.get_or_create(
            user=self.user3,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        # Activate Subscriptions
        set_subscription((self.user1, self.user2, self.user3), "default_user")

        # Create an organization
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.user1,
        )

        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Activate Subscriptions
        set_subscription(self.organization1, "default_org")

        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
            is_public=True,
        ).save()

    def test_login(self):
        response = self.client.post(
            "/api/v1/auth/login/", {"username": "user1", "password": "abc123"}
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(isinstance(response.data["token"], str))
        self.assertNotEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

    def test_login_with_email(self):
        response = self.client.post(
            "/api/v1/auth/login/", {"email": "user1@example.com", "password": "abc123"}
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(isinstance(response.data["token"], str))
        self.assertNotEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

    def test_login_qfield_expire_other_token(self):
        self.client.credentials(HTTP_USER_AGENT="qfield|dev")
        response = self.client.post(
            "/api/v1/auth/login/", {"username": "user1", "password": "abc123"}
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(isinstance(response.data["token"], str))
        self.assertNotEqual(response.data["token"], self.token1.key)
        self.assertLess(
            AuthToken.objects.get(key=self.token1.key).expires_at, timezone.now()
        )
        self.assertEqual(response.data["username"], "user1")

    def test_login_wrong_password(self):
        response = self.client.post(
            "/api/v1/auth/login/", {"username": "user1", "password": "wrong_password"}
        )
        self.assertTrue(status.is_client_error(response.status_code))
        self.assertFalse("token" in response.data)

    def test_get_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/user1/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "user1")
        self.assertEqual(response.data["type"], 1)
        self.assertTrue("email" in response.json())

    def test_get_another_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/user2/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "user2")
        self.assertEqual(response.data["type"], 1)
        self.assertFalse("email" in response.json())

    def test_get_organization(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/organization1/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "organization1")
        self.assertEqual(response.data["type"], 2)
        self.assertEqual(response.data["organization_owner"], "user1")
        self.assertEqual(len(response.data["members"]), 1)

    def test_list_users(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/")

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k["username"])

        self.assertEqual(len(json), 4)
        self.assertEqual(json[0]["username"], "organization1")
        self.assertEqual(json[1]["username"], "user1")
        self.assertEqual(json[2]["username"], "user2")
        self.assertEqual(json[3]["username"], "user3")

    def test_list_users_filter_exclude_organization(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/?exclude_organizations=1")

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k["username"])

        self.assertEqual(len(json), 3)
        self.assertEqual(json[0]["username"], "user1")
        self.assertEqual(json[1]["username"], "user2")
        self.assertEqual(json[2]["username"], "user3")

    def test_list_users_filter_for_organization(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get(
            f"/api/v1/users/?organization={self.organization1.username}"
        )

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k["username"])

        self.assertEqual(len(json), 1)
        self.assertEqual(json[0]["username"], "user3")

    def test_list_users_filter_for_project(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get(f"/api/v1/users/?project={self.project1.id}")

        self.assertTrue(status.is_success(response.status_code))

        json = response.json()
        json = sorted(json, key=lambda k: k["username"])

        self.assertEqual(len(json), 3)
        self.assertEqual(json[0]["username"], "organization1")
        self.assertEqual(json[1]["username"], "user2")
        self.assertEqual(json[2]["username"], "user3")

    def test_get_the_authenticated_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/user1/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "user1")
        self.assertEqual(response.data["type"], 1)
        self.assertTrue("email" in response.json())

    def test_update_the_authenticated_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.patch(
            "/api/v1/users/user1/",
            {
                "first_name": "Charles",
                "last_name": "Darwin",
                "email": "charles@beagle.uk",
            },
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "user1")
        self.assertEqual(response.data["type"], 1)
        self.assertEqual(response.data["first_name"], "Charles")
        self.assertEqual(response.data["last_name"], "Darwin")
        self.assertEqual(response.data["email"], "charles@beagle.uk")

    def test_update_another_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.patch(
            "/api/v1/users/user2/",
            {"first_name": "Sasha", "last_name": "Grey", "email": "sasha@grey.org"},
        )

        self.assertEqual(response.status_code, 403)

    def test_logout(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post("/api/v1/auth/logout/")
        self.assertTrue(status.is_success(response.status_code))

        # The token should not work anymore
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.get("/api/v1/users/user/")
        self.assertFalse(status.is_success(response.status_code))

    def test_api_token_auth(self):
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "user1", "password": "abc123"}
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(isinstance(response.data["token"], str))
        self.assertNotEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

    def test_api_token_auth_after_logout(self):
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "user1", "password": "abc123"}
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue(isinstance(response.data["token"], str))
        self.assertNotEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)
        response = self.client.post("/api/v1/auth/logout/")
        self.assertTrue(status.is_success(response.status_code))

        # Remove the old token from the headers
        self.client.credentials()

        response = self.client.post(
            "/api/v1/auth/token/", {"username": "user1", "password": "abc123"}
        )

        self.assertTrue(status.is_success(response.status_code))
        # The token should be different from before
        self.assertNotEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

    def test_user_account_is_created_for_each_user(self):
        self.assertTrue(UserAccount.objects.filter(user=self.user1).exists())
        self.assertTrue(UserAccount.objects.filter(user=self.user2).exists())

    def test_user_organizations(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/user1/organizations/")

        self.assertTrue(status.is_success(response.status_code))
        payload = response.json()

        self.assertEqual(len(payload), 1)

        organization = payload[0]

        self.assertEqual(organization["username"], self.organization1.username)
        self.assertEqual(organization["type"], User.Type.ORGANIZATION)
        self.assertEqual(organization["membership_role"], "admin")
        self.assertEqual(organization["membership_role_origin"], "organization_owner")
        self.assertEqual(organization["membership_is_public"], True)

    def test_duplicate_user_emails(self):
        Person.objects.create_user(
            username="u1", password="abc123", email="same@example.com"
        )

        with self.assertRaises(IntegrityError):
            Person.objects.create_user(
                username="u2", password="abc123", email="same@example.com"
            )


class CreatePersonAPITestCase(APITestCase):
    """Tests for POST /api/v1/users/ (staff-only)."""

    def setUp(self):
        setup_subscription_plans()

        self.staff_user = Person.objects.create_user(
            username="staffuser",
            password="abc123",
            email="staff@example.com",
            is_staff=True,
        )
        self.staff_token = AuthToken.objects.get_or_create(
            user=self.staff_user,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        self.regular_user = Person.objects.create_user(
            username="regularuser",
            password="abc123",
            email="regular@example.com",
        )
        self.regular_token = AuthToken.objects.get_or_create(
            user=self.regular_user,
            client_type=AuthToken.ClientType.QFIELD,
            user_agent="qfield|dev",
        )[0]

        set_subscription((self.staff_user, self.regular_user), "default_user")

    def _url(self):
        return "/api/v1/users/"

    def test_staff_can_create_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {
                "username": "newmapper",
                "password": "securepass123",
                "email": "newmapper@example.com",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["username"], "newmapper")
        self.assertTrue(Person.objects.filter(username="newmapper").exists())

    def test_create_person_with_email(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {"username": "newmapper2", "password": "pass", "email": "m@example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(
            Person.objects.get(username="newmapper2").email, "m@example.com"
        )

    def test_email_required(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(), {"username": "nomailuser", "password": "pass"}
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_person_has_accepted_tos_false(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        self.client.post(
            self._url(),
            {"username": "tosuser", "password": "pass", "email": "tos@example.com"},
        )
        self.assertFalse(Person.objects.get(username="tosuser").has_accepted_tos)

    def test_duplicate_username_returns_400(self):
        Person.objects.create_user(username="existing", password="abc123")
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {
                "username": "existing",
                "password": "pass",
                "email": "existing@example.com",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_non_staff_forbidden(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.regular_token.key)
        response = self.client.post(
            self._url(), {"username": "shouldfail", "password": "pass"}
        )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_unauthenticated_rejected(self):
        response = self.client.post(
            self._url(), {"username": "anon", "password": "pass"}
        )
        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_invalid_username_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {"username": "bad username!", "password": "pass", "email": "m@example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_username_too_short_rejected(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {"username": "ab", "password": "abc123", "email": "shortuser@example.com"},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_create_person_with_names(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {
                "username": "nameduser",
                "password": "abc123",
                "email": "nameduser@example.com",
                "first_name": "Jane",
                "last_name": "Doe",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        person = Person.objects.get(username="nameduser")
        self.assertEqual(person.first_name, "Jane")
        self.assertEqual(person.last_name, "Doe")

    def test_username_must_begin_with_letter(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {
                "username": "1badname",
                "password": "abc123",
                "email": "user1@example.com",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_duplicate_email_returns_400(self):
        Person.objects.create_user(
            username="emailowner", password="abc123", email="taken@example.com"
        )
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.post(
            self._url(),
            {
                "username": "newuser",
                "password": "abc123",
                "email": "taken@example.com",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("email", response.data)

    def test_list_still_works_for_staff(self):
        """GET /api/v1/users/ must still function after adding POST support."""
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.staff_token.key)
        response = self.client.get(self._url())
        self.assertEqual(response.status_code, status.HTTP_200_OK)
