from rest_framework.test import APITestCase

from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Secret,
)
from qfieldcloud.core.permissions_utils import (
    UserProjectRoleError,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans


class QfcTestCase(APITestCase):
    @classmethod
    def setUpTestData(cls):
        setup_subscription_plans()

        cls.u1 = Person.objects.create(username="u1", password="u1")
        cls.u2 = Person.objects.create(username="u2", password="u2")
        cls.u3 = Person.objects.create(username="u3", password="u3")
        cls.u4 = Person.objects.create(username="u4", password="u4")
        cls.u5 = Person.objects.create(username="u5", password="u5")

        cls.o1 = Organization.objects.create(username="o1", organization_owner=cls.u1)

        cls.p1 = Project.objects.create(name="p1", owner=cls.o1)
        cls.p2 = Project.objects.create(name="p2", owner=cls.o1)
        cls.p3 = Project.objects.create(name="p3", owner=cls.u1)

        members = [
            OrganizationMember(organization=cls.o1, member=cls.u2),
            OrganizationMember(organization=cls.o1, member=cls.u3),
            OrganizationMember(organization=cls.o1, member=cls.u4),
        ]

        cls.o1.members.bulk_create(members)

        collaborators = [
            ProjectCollaborator(
                project=cls.p1,
                collaborator=cls.u2,
                role=ProjectCollaborator.Roles.ADMIN,
            ),
            ProjectCollaborator(
                project=cls.p1,
                collaborator=cls.u3,
                role=ProjectCollaborator.Roles.READER,
            ),
        ]

        cls.p1.direct_collaborators.bulk_create(collaborators)

    def _create_secret(self, **kwargs) -> Secret:
        return Secret.objects.create(
            type=Secret.Type.ENVVAR,
            value="ENVVAR_VALUE",
            **kwargs,
        )

    def test_org_project_secret_available_for_user(self):
        s1 = self._create_secret(name="s1", project=self.p1)

        for user in [self.u1, self.u2, self.u3]:
            with self.subTest():
                secrets = Secret.objects.for_user_and_project(user, self.p1)

                self.assertEqual(secrets.count(), 1)
                self.assertEqual(secrets[0], s1)

    def test_raises_when_user_is_not_org_project_collaborator(self):
        _s1 = self._create_secret(name="s1", project=self.p1)

        with self.assertRaises(UserProjectRoleError):
            Secret.objects.for_user_and_project(self.u4, self.p1)

    # NOTE: this test case is commented because we don't raise anymore in such case.
    # See QF-6430.
    # def test_raises_when_user_is_not_organization_member(self):
    # _s1 = self._create_secret(name="s1", project=self.p1)

    # with self.assertRaises(UserOrganizationRoleError):
    #     Secret.objects.for_user_and_project(self.u5, self.p1)

    def test_secret_not_available_for_random_org_project(self):
        _s1 = self._create_secret(name="s1", project=self.p1)

        secrets = Secret.objects.for_user_and_project(self.u1, self.p2)

        self.assertEqual(secrets.count(), 0)

    def test_assigned_secret_overrides_org_project_secret(self):
        _project_secret = self._create_secret(name="s1", project=self.p1)
        assigned_secret = self._create_secret(
            name="s1", project=self.p1, assigned_to=self.u1
        )

        secrets = Secret.objects.for_user_and_project(self.u1, self.p1)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], assigned_secret)

    def test_multiple_secrets_per_user_in_org_project(self):
        _s1_project = self._create_secret(name="s1", project=self.p1)
        s1_assigned = self._create_secret(
            name="s1", project=self.p1, assigned_to=self.u1
        )
        s2_assigned = self._create_secret(
            name="s2", project=self.p1, assigned_to=self.u1
        )
        s3_project = self._create_secret(name="s3", project=self.p1)
        _s1_another_project = self._create_secret(
            name="s1", project=self.p2, assigned_to=self.u1
        )
        _s1_another_user = self._create_secret(
            name="s1", project=self.p1, assigned_to=self.u2
        )

        secrets = Secret.objects.for_user_and_project(self.u1, self.p1)

        self.assertEqual(secrets.count(), 3)
        self.assertEqual(secrets[0], s1_assigned)
        self.assertEqual(secrets[1], s2_assigned)
        self.assertEqual(secrets[2], s3_project)

    def test_add_project_secret_available_for_owner(self):
        s1 = self._create_secret(name="s1", project=self.p3)

        secrets = Secret.objects.for_user_and_project(self.u1, self.p3)
        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1)

    def test_assigned_secret_overrides_ind_project_secret(self):
        _s1_project = self._create_secret(name="s1", project=self.p3)
        s1_assigned = self._create_secret(
            name="s1", project=self.p3, assigned_to=self.u1
        )

        secrets = Secret.objects.for_user_and_project(self.u1, self.p3)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_assigned)

    def test_add_secrets_to_project_and_user_overrides(self):
        p = Project.objects.create(name="project", owner=self.u1)
        self._create_secret(name="s1", project=p)
        s1_assigned = self._create_secret(name="s1", project=p, assigned_to=self.u1)

        secrets = Secret.objects.for_user_and_project(self.u1, p)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_assigned)

    def test_add_secrets_to_organization_and_project_overrides(self):
        self._create_secret(name="s1", organization=self.o1)

        p = Project.objects.create(name="project", owner=self.u1)
        s1_project = self._create_secret(name="s1", project=p)

        secrets = Secret.objects.for_user_and_project(self.u1, p)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_project)

    def test_check_secrets_type_priority(self):
        p = Project.objects.create(name="project", owner=self.o1)

        s1_org = self._create_secret(name="s1", organization=self.o1)

        secrets = Secret.objects.for_user_and_project(self.u1, p)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_org)

        s1_org_assigned = self._create_secret(
            name="s1", organization=self.o1, assigned_to=self.u1
        )

        secrets = Secret.objects.for_user_and_project(self.u1, p)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_org_assigned)

        s1_project = self._create_secret(name="s1", project=p)

        secrets = Secret.objects.for_user_and_project(self.u1, p)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_project)

        s1_project_assigned = self._create_secret(
            name="s1", project=p, assigned_to=self.u1
        )

        secrets = Secret.objects.for_user_and_project(self.u1, p)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], s1_project_assigned)

    def test_check_secrets_do_not_leak(self):
        p4 = Project.objects.create(name="p4", owner=self.u2)

        p3_s1 = self._create_secret(name="p3_s1", project=self.p3)
        p4_s2 = self._create_secret(name="p4_s2", project=p4)

        secrets = Secret.objects.for_user_and_project(self.u1, self.p3)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], p3_s1)

        with self.assertRaises(UserProjectRoleError):
            secrets = Secret.objects.for_user_and_project(self.u1, p4)

            self.assertEqual(secrets.count(), 0)

        with self.assertRaises(UserProjectRoleError):
            secrets = Secret.objects.for_user_and_project(self.u2, self.p3)

            self.assertEqual(secrets.count(), 0)

        secrets = Secret.objects.for_user_and_project(self.u2, p4)

        self.assertEqual(secrets.count(), 1)
        self.assertEqual(secrets[0], p4_s2)
