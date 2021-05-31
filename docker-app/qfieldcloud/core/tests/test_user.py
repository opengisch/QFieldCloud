import logging

from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Project,
    User,
    UserAccount,
)
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.test import APITestCase

logging.disable(logging.CRITICAL)


class QfcTestCase(APITestCase):
    def setUp(self):
        # Create a user
        self.user1 = User.objects.create_user(
            username="user1", password="abc123", email="user1@example.com"
        )
        self.token1 = Token.objects.get_or_create(user=self.user1)[0]

        # Create a second user
        self.user2 = User.objects.create_user(
            username="user2", password="abc123", email="user2@example.com"
        )
        self.token2 = Token.objects.get_or_create(user=self.user2)[0]

        # Create a second user
        self.user3 = User.objects.create_user(
            username="user3", password="abc123", email="user3@example.com"
        )
        self.token3 = Token.objects.get_or_create(user=self.user3)[0]

        # Create an organization
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            user_type=2,
            organization_owner=self.user1,
        )

        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        # Set user2 as member of organization1
        OrganizationMember.objects.create(
            organization=self.organization1,
            member=self.user2,
            role=OrganizationMember.Roles.MEMBER,
            is_public=True,
        ).save()

    def tearDown(self):
        User.objects.all().delete()
        Organization.objects.all().delete()
        OrganizationMember.objects.all().delete()
        # Remove credentials
        self.client.credentials()

    def test_register_user(self):
        response = self.client.post(
            "/api/v1/auth/registration/",
            {
                "username": "pippo",
                "email": "pippo@topolinia.to",
                "password1": "secure_pass123",
                "password2": "secure_pass123",
            },
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertTrue("token" in response.data)
        self.assertTrue(User.objects.get(username="pippo"))

    def test_register_user_invalid_username(self):
        response = self.client.post(
            "/api/v1/auth/registration/",
            {
                "username": "pippo@topolinia.to",
                "email": "pippo@topolinia.to",
                "password1": "secure_pass123",
                "password2": "secure_pass123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_register_non_matching_password(self):
        response = self.client.post(
            "/api/v1/auth/registration/",
            {
                "username": "pippo",
                "email": "pippo@topolinia.to",
                "password1": "secure_pass123",
                "password2": "secure_pass456",
            },
        )
        self.assertFalse(status.is_success(response.status_code))

    def test_register_user_reserved_word(self):
        response = self.client.post(
            "/api/v1/auth/registration/",
            {
                "username": "user",
                "email": "pippo@topolinia.to",
                "password1": "secure_pass123",
                "password2": "secure_pass123",
            },
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_login(self):
        response = self.client.post(
            "/api/v1/auth/login/", {"username": "user1", "password": "abc123"}
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

    def test_login_with_email(self):
        response = self.client.post(
            "/api/v1/auth/login/", {"email": "user1@example.com", "password": "abc123"}
        )
        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["token"], self.token1.key)
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
        self.assertEqual(response.data["user_type"], 1)
        self.assertTrue("email" in response.json())

    def test_get_another_user(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/user2/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "user2")
        self.assertEqual(response.data["user_type"], 1)
        self.assertFalse("email" in response.json())

    def test_get_organization(self):
        self.client.credentials(HTTP_AUTHORIZATION="Token " + self.token1.key)

        response = self.client.get("/api/v1/users/organization1/")

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["username"], "organization1")
        self.assertEqual(response.data["user_type"], 2)
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
        self.assertEqual(response.data["user_type"], 1)
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
        self.assertEqual(response.data["user_type"], 1)
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
        self.assertEqual(response.data["token"], self.token1.key)
        self.assertEqual(response.data["username"], "user1")

    def test_api_token_auth_after_logout(self):
        response = self.client.post(
            "/api/v1/auth/token/", {"username": "user1", "password": "abc123"}
        )

        self.assertTrue(status.is_success(response.status_code))
        self.assertEqual(response.data["token"], self.token1.key)
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

        self.assertEquals(
            organization.get("username", None), self.organization1.username
        )
        self.assertEquals(organization.get("user_type", None), User.TYPE_ORGANIZATION)
        self.assertEquals(organization.get("membership_role", None), "admin")
        self.assertEquals(
            organization.get("membership_role_origin", None), "organization_owner"
        )
        self.assertEquals(organization.get("membership_is_public", None), True)
