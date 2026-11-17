import importlib
import io
import logging
from contextlib import redirect_stdout
from datetime import timedelta

from django.apps import apps
from django.db import connection
from django.test import TestCase
from django.utils import timezone

from qfieldcloud.core.models import Person
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project

logging.disable(logging.CRITICAL)

migration_0018 = importlib.import_module(
    "qfieldcloud.project.migrations.0018_project_owner_name_uniq"
)

# TODO @manylon: Remove this file once migration 0018 is applied and the constraint is enforced.


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.user1 = Person.objects.create_user(username="user1", password="abc123")
        self.user2 = Person.objects.create_user(username="user2", password="abc123")

    def _create_project_created_at(
        self, name: str, owner: Person, days_ago: int
    ) -> Project:
        project = Project.objects.create(name=name, owner=owner)
        Project.objects.filter(id=project.id).update(
            created_at=timezone.now() - timedelta(days=days_ago)
        )

        return project

    def test_migration_renames_project_names_differing_only_by_case(self):
        # The constraint added by the migration must not exist yet to create the duplicates.
        # Postgres DDL is transactional, so the test transaction restores it afterwards.
        with connection.schema_editor() as schema_editor:
            schema_editor.remove_constraint(Project, Project._meta.constraints[0])

        oldest = self._create_project_created_at("survey", self.user1, days_ago=3)
        middle = self._create_project_created_at("Survey", self.user1, days_ago=2)
        newest = self._create_project_created_at("SURVEY", self.user1, days_ago=1)
        existing_suffixed = self._create_project_created_at(
            "survey_2", self.user1, days_ago=10
        )
        other_owner = self._create_project_created_at("Survey", self.user2, days_ago=5)
        unique = self._create_project_created_at("unique", self.user1, days_ago=5)

        with redirect_stdout(io.StringIO()):
            migration_0018.rename_case_insensitive_duplicate_names(apps, None)

        names = dict(Project.objects.values_list("id", "name"))

        with self.subTest("Test the migration keeps the name of the oldest project"):
            self.assertEqual(names[oldest.id], "survey")

        with self.subTest(
            "Test the migration skips a suffix already used by the owner"
        ):
            self.assertEqual(names[middle.id], "Survey_3")
            self.assertEqual(names[newest.id], "SURVEY_4")

        with self.subTest("Test the migration keeps names without duplicates"):
            self.assertEqual(names[existing_suffixed.id], "survey_2")
            self.assertEqual(names[unique.id], "unique")

        with self.subTest("Test the migration keeps the same name of another owner"):
            self.assertEqual(names[other_owner.id], "Survey")

    def test_migration_truncates_long_names_to_fit_the_suffix(self):
        with connection.schema_editor() as schema_editor:
            schema_editor.remove_constraint(Project, Project._meta.constraints[0])

        self._create_project_created_at("a" * 255, self.user1, days_ago=2)
        newest = self._create_project_created_at("A" * 255, self.user1, days_ago=1)

        with redirect_stdout(io.StringIO()):
            migration_0018.rename_case_insensitive_duplicate_names(apps, None)

        newest.refresh_from_db(fields=["name"])
        self.assertEqual(newest.name, "A" * 253 + "_2")
