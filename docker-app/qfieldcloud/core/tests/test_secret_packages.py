import io

from rest_framework.test import APITestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Job,
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Secret,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)


class QfcTestCase(QfcFilesTestCaseMixin, APITestCase):
    # def setUp(cls):

    @classmethod
    def setUpTestData(cls):
        setup_subscription_plans()

        cls.u1 = Person.objects.create(username="u1", password="u1")
        cls.u2 = Person.objects.create(username="u2", password="u2")

        cls.o1 = Organization.objects.create(username="o1", organization_owner=cls.u1)

        cls.p1 = Project.objects.create(name="p1", owner=cls.o1)

        members = [
            OrganizationMember(organization=cls.o1, member=cls.u2),
        ]

        cls.o1.members.bulk_create(members)

        collaborators = [
            ProjectCollaborator(
                project=cls.p1,
                collaborator=cls.u2,
                role=ProjectCollaborator.Roles.ADMIN,
            ),
        ]

        cls.p1.direct_collaborators.bulk_create(collaborators)

    def _create_secret(self, **kwargs) -> Secret:
        return Secret.objects.create(
            type=Secret.Type.ENVVAR,
            **kwargs,
        )

    def _trigger_package_job(self, project: Project, user: Person) -> Job:
        # TODO: see if this is still needed, or moved to a mixin.
        auth_token = AuthToken.objects.get_or_create(
            user=user,
            client_type=AuthToken.ClientType.QFIELD,
        )[0]
        self.client.credentials(HTTP_AUTHORIZATION="Token " + auth_token.key)

        return self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": project.id,
                "type": Job.Type.PACKAGE.value,
            },
        )

    def test_create_user_level_packages(self):
        self._upload_file(
            self.u1,
            self.p1,
            "DCIM/1.jpg",
            io.FileIO(testdata_path("DCIM/1.jpg"), "rb"),
        )

        self._upload_file(
            self.u1,
            self.p1,
            "DCIM/2.jpg",
            io.FileIO(testdata_path("DCIM/2.jpg"), "rb"),
        )

        # create secrets for project and assigned to users
        self._create_secret(name="SECRET", project=self.p1)
        self._create_secret(name="SECRET", project=self.p1, assigned_to=self.u1)
        self._create_secret(name="SECRET", project=self.p1, assigned_to=self.u2)

        # create a package for the two users
        Job.objects.create(
            project=self.p1,
            created_by=self.u1,
            type=Job.Type.PACKAGE,
        )
        Job.objects.create(
            project=self.p1,
            created_by=self.u2,
            type=Job.Type.PACKAGE,
        )
        # TODO FIXME: this should work
        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        nb_latest_packages = self.p1.last_package_jobs().count()

        self.assertEquals(nb_latest_packages, 2)

        latest_packages_users = self.p1.last_package_jobs().values_list(
            "created_by", flat=True
        )

        self.assertIn(self.u1.id, latest_packages_users)
        self.assertIn(self.u2.id, latest_packages_users)
