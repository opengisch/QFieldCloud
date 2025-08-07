import io
import json
import logging
import os
import tempfile
import time

import psycopg2
from django.conf import settings
from django.http import FileResponse
from django.test import tag
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.geodb_utils import delete_db_and_role
from qfieldcloud.core.models import (
    Geodb,
    Job,
    Organization,
    OrganizationMember,
    PackageJob,
    Person,
    Project,
    ProjectCollaborator,
    Secret,
    Team,
    TeamMember,
)
from qfieldcloud.core.tests.mixins import QfcFilesTestCaseMixin
from qfieldcloud.core.utils2.jobs import repackage
from qfieldcloud.core.utils2.storage import get_stored_package_ids
from qfieldcloud.filestorage.models import File

from .utils import setup_subscription_plans, testdata_path, wait_for_project_ok_status

logging.disable(logging.CRITICAL)


class QfcTestCase(QfcFilesTestCaseMixin, APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        # Create a user
        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.token1 = AuthToken.objects.get_or_create(user=self.user1)[0]

        # Create a project
        self.project1 = Project.objects.create(
            name="project1", is_public=False, owner=self.user1
        )

        delete_db_and_role("test", self.user1.username)

        self.geodb = Geodb.objects.create(
            user=self.user1,
            dbname="test",
            hostname="geodb",
            port=5432,
        )

        self.conn = psycopg2.connect(
            dbname="test",
            user=settings.GEODB_USER,
            password=settings.GEODB_PASSWORD,
            host=settings.GEODB_HOST,
            port=settings.GEODB_PORT,
        )

    def tearDown(self):
        self.conn.close()

    def upload_files(
        self,
        token: str,
        project: Project,
        files: list[tuple[str, str]],
    ):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")
        for local_filename, remote_filename in files:
            if not local_filename:
                continue

            file = testdata_path(local_filename)
            response = self.client.post(
                f"/api/v1/files/{project.id}/{remote_filename}/",
                {"file": open(file, "rb")},
                format="multipart",
            )
            self.assertTrue(status.is_success(response.status_code))

    def upload_files_and_check_package(
        self,
        token: str,
        project: Project,
        files: list[tuple[str, str]],
        expected_files: list[str],
        job_create_error: tuple[int, str] | None = None,
        tempdir: str | None = None,
        invalid_layers: list[str] | None = None,
    ):
        self.upload_files(token, project, files)
        self.check_package(
            token, project, expected_files, job_create_error, tempdir, invalid_layers
        )

    def check_package(
        self,
        token: str,
        project: Project,
        expected_files: list[str],
        job_create_error: tuple[int, str] | None = None,
        tempdir: str | None = None,
        invalid_layers: list[str] | None = None,
    ):
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token}")

        before_started_ts = timezone.now()

        response = self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": project.id,
                "type": Job.Type.PACKAGE,
            },
        )

        if job_create_error:
            self.assertEqual(response.status_code, job_create_error[0])
            self.assertEqual(response.json()["code"], job_create_error[1])
            return
        else:
            self.assertTrue(status.is_success(response.status_code))

        job_id = response.json().get("id")

        # Wait for the worker to finish
        for _ in range(20):
            time.sleep(3)
            response = self.client.get(f"/api/v1/jobs/{job_id}/")
            payload = response.json()

            if payload["status"] == Job.Status.FINISHED:
                project.refresh_from_db()
                response = self.client.get(f"/api/v1/packages/{project.id}/latest/")
                package_payload = response.json()

                self.assertNotEquals(package_payload.get("code"), "invalid_job")
                self.assertLess(
                    package_payload["packaged_at"], timezone.now().isoformat()
                )
                self.assertGreater(
                    package_payload["packaged_at"],
                    before_started_ts.isoformat(),
                )

                sorted_downloaded_files = [
                    f["name"]
                    for f in sorted(package_payload["files"], key=lambda k: k["name"])
                ]
                sorted_expected_files = sorted(expected_files)

                self.assertListEqual(sorted_downloaded_files, sorted_expected_files)

                if tempdir:
                    for filename in expected_files:
                        response = self.client.get(
                            f"/api/v1/packages/{self.project1.id}/latest/files/{filename}/"
                        )
                        local_file = os.path.join(tempdir, filename)

                        self.assertIsInstance(response, FileResponse)

                        with open(local_file, "wb") as f:
                            for chunk in response.streaming_content:
                                f.write(chunk)

                for layer_id in package_payload["layers"]:
                    layer_data = package_payload["layers"][layer_id]

                    if invalid_layers and layer_id in invalid_layers:
                        self.assertFalse(layer_data["is_valid"], layer_id)
                    else:
                        self.assertTrue(layer_data["is_valid"], layer_id)

                return
            elif payload["status"] == Job.Status.FAILED:
                print(
                    "Job feedback:",
                    json.dumps(
                        Job.objects.get(id=job_id).feedback, sort_keys=True, indent=2
                    ),
                )
                self.fail("Worker failed with error")

        self.fail("Worker didn't finish")

    def test_list_files_for_qfield(self):
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 2056))"
        )
        self.conn.commit()
        cur.execute(
            "INSERT INTO point(id, geometry) VALUES(1, ST_GeomFromText('POINT(2725505 1121435)', 2056))"
        )
        self.conn.commit()

        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/project2.qgs", "project.qgs"),
                ("delta/points.geojson", "points.geojson"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )

    def test_list_files_missing_qgis_project_file(self):
        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/points.geojson", "points.geojson"),
            ],
            job_create_error=(400, "no_qgis_project"),
            expected_files=[],
        )

    def test_project_never_packaged(self):
        self.upload_files(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/project2.qgs", "project.qgs"),
            ],
        )

        response = self.client.get(f"/api/v1/packages/{self.project1.id}/latest/")

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()["code"], "invalid_job")

    def test_download_file_for_qfield(self):
        tempdir = tempfile.mkdtemp()

        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
                ("delta/testdata.gpkg", "testdata.gpkg"),
                ("delta/points.geojson", "points.geojson"),
                ("delta/polygons.geojson", "polygons.geojson"),
                ("delta/project.qgs", "project.qgs"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
            tempdir=tempdir,
        )

        local_file = os.path.join(tempdir, "project_qfield.qgs")
        with open(local_file) as f:
            self.assertEqual(
                f.readline().strip(),
                "<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>",
            )

    def test_list_files_for_qfield_broken_file(self):
        self.upload_files(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/broken.qgs", "broken.qgs"),
            ],
        )

        response = self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": self.project1.id,
                "type": Job.Type.PACKAGE,
            },
        )

        self.assertTrue(status.is_success(response.status_code))
        job_id = response.json().get("id")

        # Wait for the worker to finish
        for _ in range(10):
            time.sleep(3)
            response = self.client.get(
                f"/api/v1/jobs/{job_id}/",
            )
            if response.json()["status"] == "failed":
                return

        self.fail("Worker didn't finish")

    def test_create_job_twice(self):
        self.upload_files(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/project2.qgs", "project.qgs"),
                ("delta/points.geojson", "points.geojson"),
            ],
        )

        response = self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": self.project1.id,
                "type": Job.Type.PACKAGE,
            },
        )

        self.assertTrue(response.status_code, 201)

        response = self.client.post(
            "/api/v1/jobs/",
            {
                "project_id": self.project1.id,
                "type": Job.Type.PACKAGE,
            },
        )

        self.assertTrue(response.status_code, 200)

    def test_downloaded_file_has_canvas_name(self):
        tempdir = tempfile.mkdtemp()

        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
                ("delta/testdata.gpkg", "testdata.gpkg"),
                ("delta/points.geojson", "points.geojson"),
                ("delta/polygons.geojson", "polygons.geojson"),
                ("delta/project.qgs", "project.qgs"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
            tempdir=tempdir,
        )

        local_file = os.path.join(tempdir, "project_qfield.qgs")
        with open(local_file) as f:
            for line in f:
                if 'name="theMapCanvas"' in line:
                    return

    def test_download_project_with_broken_layer_datasources(self):
        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/points.geojson", "points.geojson"),
                (
                    "delta/project_broken_datasource.qgs",
                    "project_broken_datasource.qgs",
                ),
            ],
            expected_files=[
                "data.gpkg",
                "project_broken_datasource_qfield.qgs",
                "project_broken_datasource_qfield_attachments.zip",
            ],
            invalid_layers=["surfacestructure_35131bca_337c_483b_b09e_1cf77b1dfb16"],
        )

    def test_needs_repackaging_without_online_vector(self):
        self.project1.refresh_from_db()
        # newly uploaded project should always need to be packaged at least once
        self.assertTrue(self.project1.needs_repackaging(self.user1))

        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
                ("delta/testdata.gpkg", "testdata.gpkg"),
                ("delta/points.geojson", "points.geojson"),
                ("delta/polygons.geojson", "polygons.geojson"),
                ("delta/project.qgs", "project.qgs"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )

        self.project1.refresh_from_db()
        # no longer needs repackaging since geopackage layers cannot change without deltas/reupload
        self.assertFalse(self.project1.needs_repackaging(self.user1))

        self.upload_files(
            self.token1.key,
            self.project1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
            ],
        )

        self.project1.refresh_from_db()
        # a layer file changed, so we need to repackage
        self.assertTrue(self.project1.needs_repackaging(self.user1))

    def test_needs_repackaging_with_online_vector(self):
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 2056))"
        )
        self.conn.commit()
        cur.execute(
            "INSERT INTO point(id, geometry) VALUES(1, ST_GeomFromText('POINT(2725505 1121435)', 2056))"
        )
        self.conn.commit()

        self.project1.refresh_from_db()
        # newly uploaded project should always need to be packaged at least once
        self.assertTrue(self.project1.needs_repackaging(self.user1))

        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/project2.qgs", "project.qgs"),
                ("delta/points.geojson", "points.geojson"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )

        self.project1.refresh_from_db()
        # projects with online vector layer should always show as it needs repackaging
        self.assertTrue(self.project1.needs_repackaging(self.user1))

    @tag("flaky")
    def test_connects_via_pgservice(self):
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 2056))"
        )
        self.conn.commit()

        Secret.objects.create(
            name="PG_SERVICE_GEODB1",
            type=Secret.Type.PGSERVICE,
            project=self.project1,
            created_by=self.project1.owner,
            value=(
                "[geodb1]\n"
                "dbname=test\n"
                "host=geodb\n"
                "port=5432\n"
                f"user={settings.GEODB_USER}\n"
                f"password={settings.GEODB_PASSWORD}\n"
                "sslmode=disable\n"
            ),
        )

        Secret.objects.create(
            name="PG_SERVICE_GEODB2",
            type=Secret.Type.PGSERVICE,
            project=self.project1,
            created_by=self.project1.owner,
            value=(
                "[geodb2]\n"
                "dbname=test\n"
                "host=geodb\n"
                "port=5432\n"
                f"user={settings.GEODB_USER}\n"
                f"password={settings.GEODB_PASSWORD}\n"
                "sslmode=disable\n"
            ),
        )

        self.upload_files(
            self.token1.key,
            self.project1,
            files=[
                ("delta/project_pgservice.qgs", "project.qgs"),
            ],
        )

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        last_process_job = Job.objects.filter(type=Job.Type.PROCESS_PROJECTFILE).latest(
            "updated_at"
        )
        layers_by_id = last_process_job.feedback["outputs"]["project_details"][
            "project_details"
        ]["layers_by_id"]

        self.assertEqual(last_process_job.status, Job.Status.FINISHED)
        self.assertTrue(
            layers_by_id["point_6b900fa7_af52_4082_bbff_6077f4a91d02"]["is_valid"]
        )

    def test_has_online_vector_data(self):
        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 2056))"
        )
        self.conn.commit()

        self.upload_files(
            self.token1.key,
            self.project1,
            files=[
                ("delta/project2.qgs", "project.qgs"),
            ],
        )

        wait_for_project_ok_status(self.project1)

        self.project1.refresh_from_db()

        self.assertTrue(self.project1.has_online_vector_data)

    def test_has_no_online_vector_data(self):
        self.upload_files(
            self.token1.key,
            self.project1,
            files=[
                ("delta/project.qgs", "project.qgs"),
            ],
        )

        wait_for_project_ok_status(self.project1)

        self.project1.refresh_from_db()

        self.assertFalse(self.project1.has_online_vector_data)

    def test_filename_with_whitespace(self):
        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
                ("delta/testdata.gpkg", "testdata.gpkg"),
                ("delta/points.geojson", "points.geojson"),
                ("delta/polygons.geojson", "polygons.geojson"),
                ("delta/project.qgs", "project.qgs"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )

    def test_collaborator_can_package(self):
        self.upload_files(
            token=self.token1,
            project=self.project1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
                ("delta/testdata.gpkg", "testdata.gpkg"),
                ("delta/points.geojson", "points.geojson"),
                ("delta/polygons.geojson", "polygons.geojson"),
                ("delta/project.qgs", "project.qgs"),
            ],
        )

        for idx, role in enumerate(ProjectCollaborator.Roles):
            u1 = Person.objects.create(username=f"user_with_role_{idx}")
            ProjectCollaborator.objects.create(
                collaborator=u1, project=self.project1, role=role
            )

            self.check_package(
                token=AuthToken.objects.get_or_create(user=u1)[0],
                project=self.project1,
                expected_files=[
                    "data.gpkg",
                    "project_qfield.qgs",
                    "project_qfield_attachments.zip",
                ],
            )

    def test_collaborator_via_team_can_package(self):
        u1 = Person.objects.create(username="u1")
        o1 = Organization.objects.create(username="o1", organization_owner=u1)
        p1 = Project.objects.create(
            name="p1",
            owner=o1,
        )
        token_u1 = AuthToken.objects.get_or_create(user=u1)[0]

        self.upload_files(
            token=token_u1,
            project=p1,
            files=[
                ("delta/nonspatial.csv", "nonspatial.csv"),
                ("delta/testdata.gpkg", "testdata.gpkg"),
                ("delta/points.geojson", "points.geojson"),
                ("delta/polygons.geojson", "polygons.geojson"),
                ("delta/project.qgs", "project.qgs"),
            ],
        )

        for idx, role in enumerate(ProjectCollaborator.Roles):
            team = Team.objects.create(
                username=f"@{o1.username}/team_{idx}", team_organization=o1
            )
            team_user = Person.objects.create(username=f"team_user_{idx}")

            OrganizationMember.objects.create(member=team_user, organization=o1)
            TeamMember.objects.create(member=team_user, team=team)
            ProjectCollaborator.objects.create(collaborator=team, project=p1, role=role)

            self.check_package(
                token=AuthToken.objects.get_or_create(user=team_user)[0],
                project=p1,
                expected_files=[
                    "data.gpkg",
                    "project_qfield.qgs",
                    "project_qfield_attachments.zip",
                ],
            )

    def test_outdated_packaged_files_are_deleted(self):
        subscription = self.user1.useraccount.current_subscription
        subscription.plan.is_external_db_supported = True
        subscription.plan.save()

        cur = self.conn.cursor()
        cur.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 2056))"
        )
        self.conn.commit()
        cur.execute(
            "INSERT INTO point(id, geometry) VALUES(1, ST_GeomFromText('POINT(2725505 1121435)', 2056))"
        )
        self.conn.commit()

        if not self.project1.uses_legacy_storage:
            self.assertEqual(
                File.objects.filter(file_type=File.FileType.PACKAGE_FILE).count(), 0
            )

        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("delta/project2.qgs", "project.qgs"),
                ("delta/points.geojson", "points.geojson"),
            ],
            expected_files=[
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )

        old_package = PackageJob.objects.filter(project=self.project1).latest(
            "created_at"
        )

        # TODO Delete with QF-4963 Drop support for legacy storage
        if self.project1.uses_legacy_storage:
            stored_package_ids = get_stored_package_ids(self.project1)
            self.assertIn(str(old_package.id), stored_package_ids)
            self.assertEqual(len(stored_package_ids), 1)
        else:
            self.assertGreaterEqual(
                File.objects.filter(package_job=old_package).count(), 1
            )
            self.assertGreaterEqual(
                File.objects.filter(file_type=File.FileType.PACKAGE_FILE).count(), 1
            )

        self.check_package(
            self.token1.key,
            self.project1,
            [
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )

        new_package = PackageJob.objects.filter(project=self.project1).latest(
            "created_at"
        )

        # TODO Delete with QF-4963 Drop support for legacy storage
        if self.project1.uses_legacy_storage:
            stored_package_ids = get_stored_package_ids(self.project1)

            self.assertNotEqual(old_package.id, new_package.id)
            self.assertNotIn(str(old_package.id), stored_package_ids)
            self.assertIn(str(new_package.id), stored_package_ids)
            self.assertEqual(len(stored_package_ids), 1)
        else:
            self.assertEqual(File.objects.filter(package_job=old_package).count(), 0)
            self.assertGreaterEqual(
                File.objects.filter(package_job=new_package).count(), 1
            )
            self.assertGreaterEqual(
                File.objects.filter(file_type=File.FileType.PACKAGE_FILE).count(), 1
            )

    def test_package_and_project_file_attachments(self):
        # upload attachments to the project
        self.upload_files_and_check_package(
            token=self.token1.key,
            project=self.project1,
            files=[
                ("DCIM/1.jpg", "DCIM/1.jpg"),
                ("DCIM/2.jpg", "DCIM/2.jpg"),
                ("bumblebees.gpkg", "bumblebees.gpkg"),
                ("simple_bumblebees.qgs", "simple_bumblebees.qgs"),
            ],
            expected_files=[
                "data.gpkg",
                "simple_bumblebees_qfield.qgs",
                "simple_bumblebees_qfield_attachments.zip",
                "DCIM/1.jpg",
                "DCIM/2.jpg",
            ],
        )

    def test_purge_obsolete_package_files_works_fine(self):
        # create another user to check that its package files are not deleted.
        other_user = Person.objects.create_user(
            username="other_user", password="abc123"
        )
        collaborators = [
            ProjectCollaborator(
                project=self.project1,
                collaborator=other_user,
                role=ProjectCollaborator.Roles.ADMIN,
            ),
        ]
        self.project1.direct_collaborators.bulk_create(collaborators)

        # upload data & QGIS project files to the project.
        self._upload_file(
            self.user1,
            self.project1,
            "bumblebees.gpkg",
            io.FileIO(testdata_path("bumblebees.gpkg"), "rb"),
        )

        self._upload_file(
            self.user1,
            self.project1,
            "simple_bumblebees.qgs",
            io.FileIO(testdata_path("simple_bumblebees.qgs"), "rb"),
        )

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        package_job_1 = repackage(self.project1, self.user1)
        other_user_package_job = repackage(self.project1, other_user)

        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        if self.project1.uses_legacy_storage:
            # TODO Delete with QF-4963 Drop support for legacy storage
            stored_package_ids = get_stored_package_ids(self.project1)

            self.assertIn(str(package_job_1.id), stored_package_ids)
            self.assertIn(str(other_user_package_job.id), stored_package_ids)
            self.assertEquals(len(stored_package_ids), 2)

        else:
            package_files_p1_qs = File.objects.filter(
                project=self.project1,
                file_type=File.FileType.PACKAGE_FILE,
                package_job=package_job_1,
            )

            self.assertEquals(package_files_p1_qs.count(), 3)

        # repackage the project for the same user.
        package_job_2 = repackage(self.project1, self.user1)
        wait_for_project_ok_status(self.project1)
        self.project1.refresh_from_db()

        if self.project1.uses_legacy_storage:
            # TODO Delete with QF-4963 Drop support for legacy storage
            stored_package_ids = get_stored_package_ids(self.project1)

            self.assertNotIn(str(package_job_1.id), stored_package_ids)
            self.assertIn(str(package_job_2.id), stored_package_ids)
            self.assertIn(str(other_user_package_job.id), stored_package_ids)
            self.assertEquals(len(stored_package_ids), 2)

        else:
            # make sure old package files are deleted.
            package_files_p1_qs = File.objects.filter(
                project=self.project1,
                file_type=File.FileType.PACKAGE_FILE,
                package_job=package_job_1,
            )

            self.assertEquals(package_files_p1_qs.count(), 0)

            # make sure new package files are there.
            package_files_p2_qs = File.objects.filter(
                project=self.project1,
                file_type=File.FileType.PACKAGE_FILE,
                package_job=package_job_2,
            )

            self.assertEquals(package_files_p2_qs.count(), 3)

            # make sure the other user's package files are there.
            other_user_package_files_qs = File.objects.filter(
                project=self.project1,
                file_type=File.FileType.PACKAGE_FILE,
                package_job=other_user_package_job,
            )

            self.assertEquals(other_user_package_files_qs.count(), 3)

    def test_needs_repackaging(self):
        # 0. Create two users, where one owns the project and the other is a project collaborator.
        u1 = Person.objects.create(username="u1")
        u2 = Person.objects.create(username="u2")

        t1 = AuthToken.objects.get_or_create(user=u1)[0]
        t2 = AuthToken.objects.get_or_create(user=u2)[0]

        p1 = Project.objects.create(
            name="p1",
            owner=u1,
        )
        ProjectCollaborator.objects.create(
            collaborator=u2,
            project=p1,
            role=ProjectCollaborator.Roles.EDITOR,
        )

        # 1. Upload files to the project
        self.upload_files(
            t1.key,
            p1,
            files=[
                ("bumblebees.gpkg", "bumblebees.gpkg"),
                ("simple_bumblebees.qgs", "project.qgs"),
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        p1.refresh_from_db()

        self.assertTrue(p1.needs_repackaging(u1))
        self.assertTrue(p1.needs_repackaging(u2))

        # 2. Package for the first user
        self.check_package(
            t1.key,
            p1,
            [
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        # -> no secret assigned so no repackaging needed.
        p1.refresh_from_db()

        self.assertFalse(p1.needs_repackaging(u1))
        self.assertFalse(p1.needs_repackaging(u2))

        # 3. Package for the second user
        self.check_package(
            t2.key,
            p1,
            [
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        # -> no secret assigned so no repackaging needed.
        p1.refresh_from_db()

        self.assertFalse(p1.needs_repackaging(u1))
        self.assertFalse(p1.needs_repackaging(u2))

        # 4. Upload a new file to the project, so project.data_last_updated_at changes
        self.upload_files(
            t1.key,
            p1,
            files=[
                ("simple_bumblebees.qgs", "project.qgs"),
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        # -> new file uploaded so repackaging needed.
        p1.refresh_from_db()

        self.assertTrue(p1.needs_repackaging(u1))
        self.assertTrue(p1.needs_repackaging(u2))

        # 5. Create secrets for p1 and u1
        Secret.objects.create(
            type=Secret.Type.ENVVAR,
            value="PROJECT SECRET VALUE",
            name="s1",
            project=p1,
        )
        Secret.objects.create(
            type=Secret.Type.ENVVAR,
            value="USER1 SECRET VALUE",
            name="s1",
            project=p1,
            assigned_to=u1,
        )
        Secret.objects.create(
            type=Secret.Type.ENVVAR,
            value="USER2 SECRET VALUE",
            name="s1",
            project=p1,
            assigned_to=u2,
        )

        # 6. Upload a new file to the project, so project.data_last_updated_at changes
        self.upload_files(
            t1.key,
            p1,
            files=[
                ("simple_bumblebees.qgs", "project.qgs"),
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        p1.refresh_from_db()

        self.assertTrue(p1.needs_repackaging(u1))
        self.assertTrue(p1.needs_repackaging(u2))

        # 7. Package for the first user
        self.check_package(
            t1.key,
            p1,
            [
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        p1.refresh_from_db()

        self.assertFalse(p1.needs_repackaging(u1))
        self.assertTrue(p1.needs_repackaging(u2))

        # 8. Package for the second user
        self.check_package(
            t2.key,
            p1,
            [
                "data.gpkg",
                "project_qfield.qgs",
                "project_qfield_attachments.zip",
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        p1.refresh_from_db()

        self.assertFalse(p1.needs_repackaging(u1))
        self.assertFalse(p1.needs_repackaging(u2))

        # 9. Upload a new file to the project, so project.data_last_updated_at changes
        self.upload_files(
            t1.key,
            p1,
            files=[
                ("simple_bumblebees.qgs", "project.qgs"),
            ],
        )
        wait_for_project_ok_status(p1)

        # . check needs repackaging for u1 and u2
        p1.refresh_from_db()

        self.assertTrue(p1.needs_repackaging(u1))
        self.assertTrue(p1.needs_repackaging(u2))
