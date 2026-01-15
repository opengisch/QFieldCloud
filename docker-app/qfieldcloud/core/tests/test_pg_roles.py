import io

from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Organization,
    OrganizationMember,
    Person,
    Project,
    ProjectCollaborator,
    Secret,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.tests.utils import (
    get_test_postgis_connection,
    set_subscription,
    setup_subscription_plans,
    testdata_path,
    wait_for_project_ok_status,
)
from qfieldcloud.core.utils2.jobs import repackage


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.u1 = Person.objects.create(username="u1", password="u1")
        self.t1 = AuthToken.objects.get_or_create(user=self.u1)[0]

        self.u2 = Person.objects.create(username="u2", password="u2")
        self.t2 = AuthToken.objects.get_or_create(user=self.u2)[0]

        self.o1 = Organization.objects.create(username="o1", organization_owner=self.u1)

        # Activate Subscriptions
        set_subscription(self.o1, is_external_db_supported=True)

        self.p1 = Project.objects.create(name="p1", owner=self.o1)

        members = [
            OrganizationMember(organization=self.o1, member=self.u2),
        ]

        self.o1.members.bulk_create(members)

        collaborators = [
            ProjectCollaborator(
                project=self.p1,
                collaborator=self.u2,
                role=ProjectCollaborator.Roles.EDITOR,
            ),
        ]

        self.p1.direct_collaborators.bulk_create(collaborators)

        self.conn = get_test_postgis_connection()

    def test_pg_effective_user_override(self):
        # create database table and view.
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 4326))"
        )
        cur.execute("""CREATE VIEW point_view AS
SELECT
    id,
    current_user,
    session_user,
    geometry
FROM point;""")
        self.conn.commit()

        # insert dummy data.
        cur.execute(
            "INSERT INTO point(id, geometry) VALUES (1, ST_GeomFromText('POINT(1 1)', 4326))"
        )
        cur.execute(
            "INSERT INTO point(id, geometry) VALUES (2, ST_GeomFromText('POINT(2 2)', 4326))"
        )
        self.conn.commit()

        # create new role and assign grant.
        cur.execute(
            "CREATE ROLE that_user_that_overrides LOGIN PASSWORD 'the_password_of_that_user_that_overrides'"
        )
        cur.execute("GRANT SELECT ON point_view TO that_user_that_overrides")
        self.conn.commit()

        # create project-level pg_service secret.
        Secret.objects.create(
            name="PG_SERVICE_TESTDB",
            type=Secret.Type.PGSERVICE,
            project=self.p1,
            created_by=self.u1,
            value=(
                "[qfctestci]\n"
                "dbname=test_postgis_db_name\n"
                "host=test_postgis_db\n"
                "port=5432\n"
                "user=test_postgis_db_user\n"
                "password=test_postgis_db_password\n"
                "sslmode=disable\n"
            ),
        )
        self.p1.refresh_from_db()

        # upload QGIS project that uses the view.
        self._upload_file(
            self.u1,
            self.p1,
            "project.qgs",
            io.FileIO(testdata_path("override_pg_effective_user.qgs"), "rb"),
        )
        wait_for_project_ok_status(self.p1)
        self.p1.refresh_from_db()

        # check that the service is in the project details (layer).
        has_service_in_layer = False
        pg_layer_id = ""
        for layer_id, layer_details in self.p1.project_details["layers_by_id"].items():  # type: ignore
            if (
                layer_details["provider_name"] == "postgres"
                and "service='qfctestci'" in layer_details["datasource"]
                and layer_details["is_valid"]
            ):
                has_service_in_layer = True
                pg_layer_id = layer_id
                break

        self.assertTrue(has_service_in_layer)

        # create a package for user u1.
        u1_package_job = repackage(self.p1, self.u1)
        wait_for_project_ok_status(self.p1)
        u1_package_job.refresh_from_db()
        self.p1.refresh_from_db()

        # check that the package job contains successfull feedback.
        layer_details_p1 = u1_package_job.feedback["outputs"]["qfield_layer_data"][
            "layers_by_id"
        ][pg_layer_id]  # type: ignore

        self.assertTrue(layer_details_p1["is_valid"])

        # create user-level env var secret to override u2's role.
        Secret.objects.create(
            name="QFC_PG_EFFECTIVE_USER",
            type=Secret.Type.ENVVAR,
            project=self.p1,
            assigned_to=self.u2,
            created_by=self.u1,
            value="that_user_that_overrides",
        )
        self.p1.refresh_from_db()

        # create a package for user u1.
        u2_package_job = repackage(self.p1, self.u2)
        wait_for_project_ok_status(self.p1)
        u2_package_job.refresh_from_db()
        self.p1.refresh_from_db()

        # check that the package job contains successfull feedback.
        layer_details_p2 = u2_package_job.feedback["outputs"]["qfield_layer_data"][
            "layers_by_id"
        ][pg_layer_id]  # type: ignore

        self.assertTrue(layer_details_p2["is_valid"])

        # clean database structure specifically created for the test.
        cur.execute("DROP VIEW point_view")
        cur.execute("DROP TABLE point")
        cur.execute("DROP ROLE that_user_that_overrides")
