import json
import logging
import os
import time
from unittest import skipUnless

from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework import status
from rest_framework.test import APITransactionTestCase

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.models import (
    Delta,
    Job,
    Person,
    SealedSecretValue,
    Secret,
    WorkerPool,
)
from qfieldcloud.core.tests.utils import (
    get_test_postgis_connection,
    set_subscription,
    setup_subscription_plans,
    testdata_path,
)
from qfieldcloud.core.utils2.jobs import repackage
from qfieldcloud.project.models import Project, ProjectSeed

logging.disable(logging.CRITICAL)

# NOTE throwaway values that only exist for this test, CI gives the matching private key to the workers
WORKER_POOL_CREDENTIAL = "ERUjQFuOqZmnNu_3EuAty5mnPdohecYX58sJknXWlF0"
WORKER_POOL_PUBLIC_KEY = "aS4T7WZvEnpYbkvTlzdq1_b1Kt1ntHrFBs2MyL-VzVs="
JOB_TIMEOUT_S = 300
PGSERVICE_LAYER_ID = "point_6b900fa7_af52_4082_bbff_6077f4a91d02"


@skipUnless(
    os.environ.get("QFIELDCLOUD_TEST_HTTPS_WORKERS"),
    "Needs the https workers running instead of `worker_wrapper`.",
)
class QfcTestCase(APITransactionTestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user = Person.objects.create_user(username="user1", password="abc123")
        set_subscription(self.user, is_external_db_supported=True)
        self.project = Project.objects.create(name="p1", owner=self.user)
        self.pool = WorkerPool.objects.create(
            name="global",
            public_key=WORKER_POOL_PUBLIC_KEY,
            credential_hash=WorkerPool.hash_credential(WORKER_POOL_CREDENTIAL),
        )

        token = AuthToken.objects.get_or_create(user=self.user)[0]
        self.client.credentials(HTTP_AUTHORIZATION=f"Token {token.key}")

    def _upload_file(self, local_filename: str, remote_filename: str) -> None:
        with open(testdata_path(local_filename), "rb") as file:
            response = self.client.post(
                f"/api/v1/files/{self.project.id}/{remote_filename}/",
                {"file": file},
                format="multipart",
            )

        self.assertTrue(status.is_success(response.status_code), response.content)

    def _wait_for_jobs(self, project: Project) -> None:
        finished = [Job.Status.FINISHED, Job.Status.FAILED, Job.Status.STOPPED]
        deadline = time.monotonic() + JOB_TIMEOUT_S

        while Job.objects.filter(project=project).exclude(status__in=finished).exists():
            if time.monotonic() > deadline:
                self.fail(f"The jobs of {project.name} did not finish in time.")

            time.sleep(1)

        project.refresh_from_db()

    def _upload_deltafile(self) -> None:
        with open(testdata_path("delta/deltas/singlelayer_singledelta.json")) as file:
            deltafile = json.load(file)

        deltafile["project"] = str(self.project.id)
        response = self.client.post(
            f"/api/v1/deltas/{self.project.id}/",
            {
                "file": SimpleUploadedFile(
                    "deltas.json", json.dumps(deltafile).encode(), "application/json"
                )
            },
            format="multipart",
        )

        self.assertTrue(status.is_success(response.status_code), response.content)

    def test_all_job_types_run_on_the_workers(self):
        for filename in [
            "points.geojson",
            "polygons.geojson",
            "testdata.gpkg",
            "nonspatial.csv",
            "project.qgs",
        ]:
            self._upload_file(f"delta/{filename}", filename)

        self._wait_for_jobs(self.project)

        repackage(self.project, self.user)
        self._wait_for_jobs(self.project)

        self._upload_deltafile()
        self._wait_for_jobs(self.project)

        clone = Project.objects.create(name="clone", owner=self.user)
        ProjectSeed.objects.create(
            project=clone,
            clone_from_project=self.project,
            settings={"schemaId": ProjectSeed.SETTINGS_SCHEMA_ID},
        )
        Job.objects.create(
            project=clone, type=Job.Type.CREATE_PROJECT, created_by=self.user
        )
        self._wait_for_jobs(clone)

        jobs = Job.objects.filter(project__in=[self.project, clone])

        self.assertEqual({job.type for job in jobs}, set(Job.Type))

        for job in jobs:
            self.assertEqual(job.status, Job.Status.FINISHED, job.feedback)
            self.assertEqual(job.worker_pool, self.pool)

        self.assertEqual(
            Delta.objects.get(project=self.project).last_status, Delta.Status.APPLIED
        )

    def test_jobs_read_sealed_secrets(self):
        conn = get_test_postgis_connection()
        self.addCleanup(conn.close)
        cursor = conn.cursor()
        cursor.execute(
            "CREATE TABLE point (id integer primary key, geometry geometry(point, 2056))"
        )
        conn.commit()

        envvar_secret = Secret.objects.create(
            name="CHECK_SECRET",
            type=Secret.Type.ENVVAR,
            project=self.project,
            created_by=self.user,
            value="the-secret-value",
        )

        for service in ["geodb1", "geodb2"]:
            Secret.objects.create(
                name=f"PG_{service.upper()}",
                type=Secret.Type.PGSERVICE,
                project=self.project,
                created_by=self.user,
                value=(
                    f"[{service}]\n"
                    "dbname=test_postgis_db_name\n"
                    "host=test_postgis_db\n"
                    "port=5432\n"
                    "user=test_postgis_db_user\n"
                    "password=test_postgis_db_password\n"
                    "sslmode=disable\n"
                ),
            )

        self._upload_file("delta/project_pgservice.qgs", "project.qgs")
        self._wait_for_jobs(self.project)

        job = Job.objects.get(project=self.project)
        layers = job.feedback["outputs"]["project_details"]["project_details"][
            "layers_by_id"
        ]

        self.assertEqual(job.status, Job.Status.FINISHED, job.feedback)
        self.assertIsNotNone(job.secrets_fetched_at)
        self.assertIn("CHECK_SECRET", job.output)
        self.assertNotIn("the-secret-value", job.output)
        self.assertTrue(layers[PGSERVICE_LAYER_ID]["is_valid"])

        SealedSecretValue.objects.filter(secret=envvar_secret).delete()

        package_job = repackage(self.project, self.user)
        self._wait_for_jobs(self.project)
        package_job.refresh_from_db()

        self.assertEqual(package_job.status, Job.Status.FAILED)
        self.assertEqual(package_job.feedback["error_type"], "MISSING_SECRETS")
        self.assertIn("CHECK_SECRET", package_job.feedback["error"])
