import logging

from django.test import TestCase, tag
from django.urls import reverse

from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    ProjectCollaborator,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.enums import ProjectCollaboratorRole
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


@tag("custom_admin")
class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="superuser", password="secret", email="super@example.com"
        )
        self.user1 = Person.objects.create_user(
            username="user1", password="abc123", email="user1@example.com"
        )
        self.user2 = Person.objects.create_user(
            username="user2", password="abc123", email="user2@example.com"
        )

        self.url = reverse("admin:global_search")

    def test_admin_sidebar_links_to_global_search(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(reverse("admin:index"))

        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, f'href="{self.url}"')

    def test_global_search_requires_staff_login(self):
        login_url = f"{reverse('admin:login')}?next={self.url}"

        with self.subTest("Test the view redirects an anonymous user to login"):
            resp = self.client.get(self.url)

            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.url, login_url)

        with self.subTest("Test the view redirects a non-staff user to login"):
            self.client.force_login(self.user1)

            resp = self.client.get(self.url)

            self.assertEqual(resp.status_code, 302)
            self.assertEqual(resp.url, login_url)

    def test_global_search_renders_without_query(self):
        self.client.force_login(self.superuser)

        resp = self.client.get(self.url)

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.context["query"], "")
        self.assertIsNone(resp.context["person_result"])
        self.assertEqual(resp.context["results"], {})

    def test_global_search_finds_person(self):
        self.client.force_login(self.superuser)

        with self.subTest("Test the view finds a person by case-insensitive username"):
            resp = self.client.get(self.url, {"q": "USER1"})

            self.assertEqual(resp.context["person_result"], self.user1)

        with self.subTest("Test the view finds a person by case-insensitive email"):
            resp = self.client.get(self.url, {"q": "User1@Example.com"})

            self.assertEqual(resp.context["person_result"], self.user1)

        with self.subTest("Test the view finds no person for a partial username"):
            resp = self.client.get(self.url, {"q": "user"})

            self.assertIsNone(resp.context["person_result"])

    def test_global_search_finds_related_objects_of_the_searched_person(self):
        project1 = Project.objects.create(name="project1", owner=self.user1)
        project2 = Project.objects.create(name="project2", owner=self.user2)
        org1 = Organization.objects.create(
            username="org1", organization_owner=self.user1
        )
        org2 = Organization.objects.create(
            username="org2", organization_owner=self.user2
        )

        # user1 is related to user2's project and organization, but doesn't own them
        ProjectCollaborator.objects.create(
            collaborator=self.user1,
            project=project2,
            role=ProjectCollaboratorRole.EDITOR,
        )
        OrganizationMember.objects.create(organization=org2, member=self.user1)

        self.client.force_login(self.superuser)

        resp = self.client.get(self.url, {"q": "user1@example.com"})
        results = resp.context["results"]

        with self.subTest("Test the view finds the searched person"):
            self.assertEqual(resp.context["person_result"], self.user1)

        with self.subTest("Test the view lists only the projects owned by the person"):
            projects = results["projects"]["page_obj"]

            self.assertEqual(len(projects), 1)
            self.assertEqual(projects[0], project1)

        with self.subTest(
            "Test the view leaves out projects the person only collaborates on"
        ):
            self.assertNotIn(project2, results["projects"]["page_obj"])

        with self.subTest(
            "Test the view lists only the organizations owned by the person"
        ):
            organizations = results["organizations"]["page_obj"]

            self.assertEqual(len(organizations), 1)
            self.assertEqual(organizations[0], org1)

        with self.subTest(
            "Test the view leaves out organizations the person is only a member of"
        ):
            self.assertNotIn(org2, results["organizations"]["page_obj"])

        with self.subTest("Test the view lists only the person's own subscription"):
            subscriptions = results["subscriptions"]["page_obj"]

            self.assertEqual(len(subscriptions), 1)
            self.assertEqual(subscriptions[0].account.user.username, "user1")
