import logging

from django.test import TestCase
from drf_spectacular.generators import SchemaGenerator

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.schema = SchemaGenerator().get_schema(request=None, public=True)

    def _operation(self, path, method="post"):
        return self.schema["paths"][f"/api/v1/worker/{path}"][method]

    def test_worker_pool_credential_has_its_own_scheme(self):
        schemes = self.schema["components"]["securitySchemes"]

        self.assertIn('"WorkerPool"', schemes["workerPoolAuth"]["description"])
        self.assertIn('"Token"', schemes["tokenAuth"]["description"])

    def test_pool_endpoints_use_the_pool_credential(self):
        for path, method in [
            ("key/", "put"),
            ("jobs/claim/", "post"),
            ("jobs/{job_id}/secrets/", "post"),
            ("jobs/{job_id}/deltafile/", "post"),
        ]:
            with self.subTest(path=path):
                self.assertEqual(
                    self._operation(path, method)["security"], [{"workerPoolAuth": []}]
                )

    def test_complete_uses_the_job_token(self):
        self.assertEqual(
            self._operation("jobs/{job_id}/complete/")["security"],
            [{"tokenAuth": []}],
        )

    def test_responses_describe_what_the_endpoints_return(self):
        claim = self._operation("jobs/claim/")["responses"]

        self.assertEqual(set(claim), {"200", "204"})
        self.assertIn(
            "ClaimedJob", claim["200"]["content"]["application/json"]["schema"]["$ref"]
        )
        self.assertEqual(set(self._operation("key/", "put")["responses"]), {"204"})
        self.assertEqual(
            set(self._operation("jobs/{job_id}/complete/")["responses"]), {"204"}
        )
        self.assertIn(
            "JobSecrets",
            self._operation("jobs/{job_id}/secrets/")["responses"]["200"]["content"][
                "application/json"
            ]["schema"]["$ref"],
        )
