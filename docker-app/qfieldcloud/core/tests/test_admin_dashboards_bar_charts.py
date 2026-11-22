from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone

from qfieldcloud.core.admin_dashboards.new_jobs import (
    compute_new_jobs_stats,
)
from qfieldcloud.core.admin_dashboards.new_projects import (
    compute_new_projects_stats,
)
from qfieldcloud.core.models import Job, Person, ProcessProjectfileJob
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project


def get_noon_days_ago(days_ago: int) -> datetime:
    # noon keeps the local calendar day, whatever the time zone and daylight saving time
    day = timezone.localdate() - timedelta(days=days_ago)

    return timezone.make_aware(datetime.combine(day, time(12)))


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()
        self.owner = Person.objects.create_user(
            username="owner", password="abc123", email="owner@example.com"
        )

    def create_project(self, name: str, created_at: datetime) -> Project:
        project = Project.objects.create(name=name, owner=self.owner)
        Project.objects.filter(pk=project.pk).update(created_at=created_at)

        return project

    def create_job(self, job_type: Job.Type, project: Project, days_ago: int) -> None:
        job = ProcessProjectfileJob.objects.create(
            project=project, created_by=self.owner
        )
        Job.objects.filter(pk=job.pk).update(
            type=job_type, created_at=get_noon_days_ago(days_ago)
        )

    def test_compute_new_projects_stats_counts_projects_per_calendar_day(self):
        self.create_project("today1", get_noon_days_ago(0))
        self.create_project("today2", get_noon_days_ago(0))
        self.create_project("first_day", get_noon_days_ago(6))

        stats = compute_new_projects_stats(period_duration=timedelta(days=7))

        self.assertEqual(stats["counts"], [1, 0, 0, 0, 0, 0, 2])

    def test_compute_new_projects_stats_counts_projects_per_hour_for_a_day(self):
        self.create_project("last_hour", timezone.now() - timedelta(hours=1))

        stats = compute_new_projects_stats(period_duration=timedelta(hours=24))

        with self.subTest("Test a day has a bar per hour"):
            self.assertEqual(len(stats["counts"]), 24)

        with self.subTest(
            "Test the project of an hour ago is in the bar before the current hour"
        ):
            self.assertEqual(stats["counts"][22], 1)

    def test_compute_new_jobs_stats_counts_jobs_per_type_and_calendar_day(self):
        project = self.create_project("project", get_noon_days_ago(30))
        Job.objects.all().delete()

        self.create_job(Job.Type.PACKAGE, project, days_ago=0)
        self.create_job(Job.Type.PROCESS_PROJECTFILE, project, days_ago=2)

        stats = compute_new_jobs_stats(period_duration=timedelta(days=7))

        self.assertEqual(
            stats["counts_by_type"],
            {
                "package": [0, 0, 0, 0, 0, 0, 1],
                "delta_apply": [0, 0, 0, 0, 0, 0, 0],
                "process_projectfile": [0, 0, 0, 0, 1, 0, 0],
                "create_project": [0, 0, 0, 0, 0, 0, 0],
            },
        )
