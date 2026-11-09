import logging

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from qfieldcloud.core.models import (
    Organization,
    Person,
    SealedSecretValue,
    Secret,
    WorkerPool,
)
from qfieldcloud.core.tests.test_sealed_box import TEST_PUBLIC_KEY
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.core.worker_pools import get_resources_affected_by_new_pool
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.superuser = Person.objects.create_superuser(
            username="super", password="abc123"
        )
        self.client.force_login(self.superuser)
        self.organization1 = Organization.objects.create(
            username="organization1",
            password="abc123",
            type=2,
            organization_owner=self.superuser,
        )
        self.project1 = Project.objects.create(name="p1", owner=self.organization1)
        self.global_pool = WorkerPool.objects.create(
            name="global", public_key=TEST_PUBLIC_KEY
        )
        self.secret = Secret.objects.create(
            name="SECRET1",
            type=Secret.Type.ENVVAR,
            value="value",
            project=self.project1,
        )

    def _add_pool(self, **data):
        return self.client.post(
            reverse("admin:core_workerpool_add"),
            {"name": "own", "organization": self.organization1.pk, **data},
        )

    def _reset_key(self, **data):
        return self.client.post(
            reverse("admin:core_workerpool_changelist"),
            {
                "action": "reset_key",
                "_selected_action": [self.global_pool.pk],
                **data,
            },
        )

    def test_affected_resources_include_all_projects_of_organization_secret(self):
        Secret.objects.create(
            name="SECRET2",
            type=Secret.Type.ENVVAR,
            value="value",
            organization=self.organization1,
        )
        project2 = Project.objects.create(name="p2", owner=self.organization1)

        affected = get_resources_affected_by_new_pool(self.organization1)

        self.assertEqual(affected.secrets.count(), 2)
        self.assertCountEqual(affected.projects, [self.project1, project2])

    def test_adding_organization_pool_asks_for_confirmation(self):
        response = self._add_pool()

        self.assertTemplateUsed(response, "admin/worker_pool_confirm.html")
        self.assertContains(response, "SECRET1")
        self.assertContains(response, "p1")
        self.assertFalse(WorkerPool.objects.filter(name="own").exists())

    def test_adding_organization_pool_after_confirmation(self):
        response = self._add_pool(_confirmed="yes")

        self.assertTemplateUsed(response, "admin/worker_pool_credentials.html")
        self.assertTrue(WorkerPool.objects.filter(name="own").exists())

    def test_adding_organization_pool_without_secrets_does_not_ask(self):
        self.secret.delete()

        response = self._add_pool()

        self.assertTemplateUsed(response, "admin/worker_pool_credentials.html")

    def test_reset_key_asks_for_confirmation(self):
        response = self._reset_key()

        self.assertTemplateUsed(response, "admin/worker_pool_confirm.html")
        self.assertContains(response, "SECRET1")
        self.global_pool.refresh_from_db()
        self.assertEqual(self.global_pool.public_key, TEST_PUBLIC_KEY)
        self.assertTrue(SealedSecretValue.objects.exists())

    def test_reset_key_after_confirmation_deletes_sealed_values(self):
        self._reset_key(_confirmed="yes")

        self.global_pool.refresh_from_db()
        self.assertEqual(self.global_pool.public_key, "")
        self.assertFalse(SealedSecretValue.objects.exists())

    def test_delete_page_lists_affected_secrets(self):
        response = self.client.get(
            reverse("admin:core_workerpool_delete", args=[self.global_pool.pk])
        )

        self.assertContains(response, "SECRET1")
        self.assertContains(response, "must be entered again")

    def test_delete_page_does_not_warn_without_secrets(self):
        self.secret.delete()

        response = self.client.get(
            reverse("admin:core_workerpool_delete", args=[self.global_pool.pk])
        )

        self.assertNotContains(response, "must be entered again")

    def test_organization_page_shows_global_without_own_pool(self):
        response = self.client.get(
            reverse("admin:core_organization_change", args=[self.organization1.pk])
        )

        self.assertContains(response, "Global")

    def test_organization_page_links_own_pool(self):
        pool = WorkerPool.objects.create(name="own", organization=self.organization1)

        response = self.client.get(
            reverse("admin:core_organization_change", args=[self.organization1.pk])
        )

        self.assertContains(
            response, reverse("admin:core_workerpool_change", args=[pool.pk])
        )
        self.assertContains(response, "no key registered")

    def _enter_secret_value(self):
        return self.client.post(
            reverse("admin:core_secret_change", args=[self.secret.pk]),
            {"value": "new value"},
            follow=True,
        )

    def test_saving_secret_warns_when_pool_has_no_key(self):
        self._reset_key(_confirmed="yes")

        response = self._enter_secret_value()

        self.assertContains(response, "has no key yet")

    def test_saving_secret_does_not_warn_when_pool_has_key(self):
        response = self._enter_secret_value()

        self.assertNotContains(response, "has no key yet")

    def test_secret_does_not_need_reentering_when_sealed(self):
        self.assertFalse(self.secret.needs_reentering)

    def test_secret_needs_reentering_after_key_reset(self):
        self._reset_key(_confirmed="yes")

        self.assertTrue(self.secret.needs_reentering)

    def test_secret_needs_reentering_after_moving_to_own_pool(self):
        WorkerPool.objects.create(
            name="own", organization=self.organization1, public_key=TEST_PUBLIC_KEY
        )

        self.assertTrue(self.secret.needs_reentering)

    def test_secret_does_not_need_reentering_without_any_pool(self):
        WorkerPool.objects.all().delete()

        self.assertFalse(self.secret.needs_reentering)

    def test_entering_secret_again_clears_the_label(self):
        self._reset_key(_confirmed="yes")
        self.global_pool.public_key = TEST_PUBLIC_KEY
        self.global_pool.save()

        self.secret.save()

        self.assertFalse(self.secret.needs_reentering)

    def test_secret_sealed_for_another_key_needs_reentering(self):
        SealedSecretValue.objects.update(key_id="0" * 64)

        self.assertTrue(self.secret.needs_reentering)

    def test_organization_secret_on_own_pool_does_not_need_reentering(self):
        WorkerPool.objects.create(
            name="own", organization=self.organization1, public_key=TEST_PUBLIC_KEY
        )
        secret = Secret.objects.create(
            name="SECRET2",
            type=Secret.Type.ENVVAR,
            value="value",
            organization=self.organization1,
        )

        self.assertFalse(secret.needs_reentering)
        self.assertTrue(self.secret.needs_reentering)

    def _count_queries(self, url: str) -> int:
        with CaptureQueriesContext(connection) as context:
            response = self.client.get(url)

        self.assertEqual(response.status_code, 200)

        return len(context.captured_queries)

    def test_secret_lists_do_not_query_per_secret(self):
        for url in (
            reverse("admin:core_secret_changelist"),
            reverse("admin:project_project_change", args=[self.project1.pk]),
        ):
            with self.subTest(url=url):
                queries_for_one = self._count_queries(url)

                for index in range(3):
                    Secret.objects.create(
                        name=f"MORE_SECRET{index}",
                        type=Secret.Type.ENVVAR,
                        value="value",
                        project=self.project1,
                    )

                self.assertEqual(self._count_queries(url), queries_for_one)
                Secret.objects.filter(name__startswith="MORE_SECRET").delete()
