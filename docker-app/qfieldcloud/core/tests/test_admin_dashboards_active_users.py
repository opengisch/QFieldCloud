import uuid
from datetime import timedelta

from django.http import QueryDict
from django.test import TestCase
from django.utils import timezone

from qfieldcloud.authentication.models import AuthToken
from qfieldcloud.core.admin_dashboards import clear_admin_dashboards_cache
from qfieldcloud.core.admin_dashboards.active_users import (
    compute_active_users_stats,
    get_active_users_stats,
)
from qfieldcloud.core.admin_dashboards.utils import get_period
from qfieldcloud.core.models import (
    Delta,
    Job,
    Organization,
    Person,
    ProcessProjectfileJob,
)
from qfieldcloud.core.tests.utils import setup_subscription_plans
from qfieldcloud.project.models import Project


def create_person(username: str, **kwargs) -> Person:
    return Person.objects.create_user(
        username=username,
        password="abc123",
        email=f"{username}@example.com",
        **kwargs,
    )


def set_last_login(user: Person | Organization, days_ago: int) -> None:
    Person.objects.filter(pk=user.pk).update(
        last_login=timezone.now() - timedelta(days=days_ago)
    )


def create_used_token(
    user: Person, client_type: AuthToken.ClientType, days_ago: int
) -> None:
    token = AuthToken.objects.create(user=user, client_type=client_type)
    AuthToken.objects.filter(pk=token.pk).update(
        last_used_at=timezone.now() - timedelta(days=days_ago)
    )


def create_job(project: Project, created_by: Person, days_ago: int) -> None:
    job = ProcessProjectfileJob.objects.create(project=project, created_by=created_by)
    Job.objects.filter(pk=job.pk).update(
        created_at=timezone.now() - timedelta(days=days_ago)
    )


class QfcTestCase(TestCase):
    def setUp(self):
        setup_subscription_plans()
        # memcached is not reset between tests
        clear_admin_dashboards_cache()

    def test_compute_active_users_stats_counts_distinct_active_persons(self):
        web_user = create_person("web_user")
        set_last_login(web_user, days_ago=1)

        qfield_user = create_person("qfield_user")
        create_used_token(qfield_user, AuthToken.ClientType.QFIELD, days_ago=2)

        multi_user = create_person("multi_user")
        set_last_login(multi_user, days_ago=1)
        create_used_token(multi_user, AuthToken.ClientType.QFIELD, days_ago=1)
        create_used_token(multi_user, AuthToken.ClientType.QFIELD, days_ago=3)
        create_used_token(multi_user, AuthToken.ClientType.QFIELDSYNC, days_ago=1)

        outdated_user = create_person("outdated_user")
        set_last_login(outdated_user, days_ago=31)
        create_used_token(outdated_user, AuthToken.ClientType.QFIELD, days_ago=31)

        deactivated_user = create_person("deactivated_user", is_active=False)
        set_last_login(deactivated_user, days_ago=1)
        create_used_token(deactivated_user, AuthToken.ClientType.QFIELD, days_ago=1)

        worker_only_user = create_person("worker_only_user")
        create_used_token(worker_only_user, AuthToken.ClientType.WORKER, days_ago=1)

        organization = Organization.objects.create(
            username="org1", organization_owner=create_person("org_owner")
        )
        set_last_login(organization, days_ago=1)

        staff_user = create_person("staff_user", is_staff=True)
        set_last_login(staff_user, days_ago=1)

        project = Project.objects.create(name="project", owner=qfield_user)
        create_job(project, created_by=qfield_user, days_ago=1)
        create_job(project, created_by=staff_user, days_ago=1)
        delta_id = uuid.uuid4()
        Delta.objects.create(
            deltafile_id=delta_id,
            project=project,
            client_id=delta_id,
            created_by=outdated_user,
            content={},
        )

        stats = compute_active_users_stats(period_duration=timedelta(days=30))

        with self.subTest(
            "Test that the 'total' counts each active person once and skips 'outdated', 'deactivated', 'worker-only' and 'organization' accounts"
        ):
            self.assertEqual(stats["total_active_users"], 4)

        with self.subTest("Test the web login count includes only actual web logins"):
            self.assertEqual(stats["web_login_count"], 3)

        with self.subTest(
            "Test the project active count includes only signed-in users with a delta or job"
        ):
            self.assertEqual(stats["project_active_count"], 2)

        with self.subTest("Test the client type counts each user once per client type"):
            self.assertEqual(
                stats["client_type_counts"],
                {
                    "browser": 0,
                    "cli": 0,
                    "sdk": 0,
                    "qfield": 2,
                    "qfieldsync": 1,
                    "unknown": 0,
                },
            )

    def test_get_active_users_stats_serves_cached_stats_until_cleared(self):
        set_last_login(create_person("user1"), days_ago=1)
        get_active_users_stats("30d")
        set_last_login(create_person("user2"), days_ago=1)

        with self.subTest(
            "Test the next read returns the cached stats without querying"
        ):
            with self.assertNumQueries(0):
                stats = get_active_users_stats("30d")

            self.assertEqual(stats["total_active_users"], 1)

        with self.subTest(
            "Test clearing the cache makes the next read recompute the stats"
        ):
            clear_admin_dashboards_cache()

            self.assertEqual(get_active_users_stats("30d")["total_active_users"], 2)

    def test_get_period_falls_back_to_30_days_for_an_unknown_period(self):
        self.assertEqual(get_period(QueryDict("period=365d")), "30d")
