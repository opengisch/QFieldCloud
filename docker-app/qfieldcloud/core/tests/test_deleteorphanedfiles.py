"""
Todo:
    * Delete with QF-4963 Drop support for legacy storage
"""

import io

from django.conf import settings
from django.core.management import call_command
from django.test import TestCase

from qfieldcloud.core.models import Person, Project
from qfieldcloud.core.utils import get_project_files_count, get_s3_bucket
from qfieldcloud.core.utils2 import storage

from .utils import set_subscription, setup_subscription_plans


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()

        self.u1 = Person.objects.create(username="u1")
        set_subscription(self.u1, "default_user")
        self.projects: list[Project] = []

        get_s3_bucket().objects.filter(Prefix="projects/").delete()

        self.generate_projects(2)

    def generate_projects(self, count: int):
        offset = len(self.projects)
        for i in range(1, count + 1):
            p = Project.objects.create(
                name=f"p{offset + i}",
                owner=self.u1,
                file_storage=settings.LEGACY_STORAGE_NAME,
            )
            self.projects.append(p)
            file = io.BytesIO(b"Hello world!")
            storage.upload_project_file(p, file, "project.qgs")

    def call_command(self, *args, **kwargs):
        out = io.StringIO()
        call_command(
            "deleteorphanedfiles",
            *args,
            stdout=out,
            stderr=out,
            **kwargs,
        )
        return out.getvalue()

    def test_nothing_to_delete(self):
        project_ids = sorted([str(p.id) for p in self.projects])

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(self.projects[1].project_files_count, 1)

        out = self.call_command()

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Checking the last 2 project id(s) from the storage...",
                    "No project files to delete.",
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(self.projects[1].project_files_count, 1)

    def test_dry_run(self):
        project_ids = sorted([str(p.id) for p in self.projects])

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(self.projects[1].project_files_count, 1)

        out = self.call_command(dry_run=True)

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Dry run, no files will be deleted.",
                    "Checking the last 2 project id(s) from the storage...",
                    "No project files to delete.",
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(self.projects[1].project_files_count, 1)

    def test_delete_files(self):
        project_ids = sorted([str(p.id) for p in self.projects])
        Project.objects.filter(id__in=project_ids).delete()

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(get_project_files_count(project_ids[1]), 1)

        out = self.call_command()

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Checking the last 2 project id(s) from the storage...",
                    f'Deleting project files for "{project_ids[0]}"...',
                    f'Deleting project files for "{project_ids[1]}"...',
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 0)
        self.assertEqual(get_project_files_count(project_ids[1]), 0)

    def test_delete_files_dry_run(self):
        project_ids = sorted([str(p.id) for p in self.projects])
        Project.objects.filter(id__in=project_ids).delete()

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(get_project_files_count(project_ids[1]), 1)

        out = self.call_command(dry_run=True)

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Dry run, no files will be deleted.",
                    "Checking the last 2 project id(s) from the storage...",
                    f'Deleting project files for "{project_ids[0]}"...',
                    f'Deleting project files for "{project_ids[1]}"...',
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(get_project_files_count(project_ids[1]), 1)

    def test_invalid_uuid(self):
        project_ids = sorted([str(p.id) for p in self.projects])

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(self.projects[1].project_files_count, 1)

        file = io.BytesIO(b"Hello world!")
        storage.upload_file(file, "projects/strangename/project.qgs")

        out = self.call_command()

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Invalid uuid: strangename/project.qgs",
                    "Checking the last 2 project id(s) from the storage...",
                    "No project files to delete.",
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(self.projects[1].project_files_count, 1)

    def test_batches(self):
        self.generate_projects(2)
        project_ids = sorted([str(p.id) for p in self.projects])
        Project.objects.filter(id__in=project_ids[:2]).delete()

        self.assertEqual(get_project_files_count(project_ids[0]), 1)
        self.assertEqual(get_project_files_count(project_ids[1]), 1)
        self.assertEqual(get_project_files_count(project_ids[2]), 1)
        self.assertEqual(get_project_files_count(project_ids[3]), 1)

        out = self.call_command(limit=2)

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Checking a batch of 2 project ids from the storage...",
                    "Checking a batch of 2 project ids from the storage...",
                    f'Deleting project files for "{project_ids[0]}"...',
                    f'Deleting project files for "{project_ids[1]}"...',
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 0)
        self.assertEqual(get_project_files_count(project_ids[1]), 0)
        self.assertEqual(get_project_files_count(project_ids[2]), 1)
        self.assertEqual(get_project_files_count(project_ids[3]), 1)

    def test_deletes_extra_files_on_second_level(self):
        file = io.BytesIO(b"Hello world!")
        storage.upload_project_file(self.projects[0], file, "inner/path/data.txt")

        project_ids = sorted([str(p.id) for p in self.projects])
        Project.objects.filter(id__in=project_ids).delete()

        self.assertEqual(get_project_files_count(str(self.projects[0].id)), 2)
        self.assertEqual(get_project_files_count(str(self.projects[1].id)), 1)

        out = self.call_command()

        self.assertEqual(
            out.strip(),
            "\n".join(
                [
                    "Checking the last 2 project id(s) from the storage...",
                    f'Deleting project files for "{project_ids[0]}"...',
                    f'Deleting project files for "{project_ids[1]}"...',
                ]
            ),
        )

        self.assertEqual(get_project_files_count(project_ids[0]), 0)
        self.assertEqual(get_project_files_count(project_ids[1]), 0)
