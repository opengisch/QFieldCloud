import io
import os
import tempfile
import zipfile
from collections.abc import Iterable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from time import sleep
from typing import IO

import psycopg2
from django.conf import settings
from django.utils import timezone

from qfieldcloud.core.models import Job, User
from qfieldcloud.project.models import Project
from qfieldcloud.subscription.models import Plan, Subscription


def testdata_path(path):
    basepath = os.path.dirname(os.path.abspath(__file__))
    return os.path.realpath(os.path.join(basepath, "testdata", path))


def get_filename(response):
    content_disposition = response.headers.get("Content-Disposition")

    if content_disposition:
        parts = content_disposition.split("filename=")

        if len(parts) == 2:
            return parts[1][1:-1]

    return None


def setup_subscription_plans():
    Plan.objects.update(trial_plan=None)
    Plan.objects.all().delete()
    Plan.objects.bulk_create(
        [
            Plan(
                code="default_user",
                display_name="default user (autocreated)",
                storage_mb=10,
                storage_threshold_warning_bytes=2_000_000,
                storage_threshold_critical_bytes=1_000_000,
                is_default=True,
                is_public=False,
                user_type=User.Type.PERSON,
                initial_subscription_status=Subscription.Status.ACTIVE_PAID,
            ),
            Plan(
                code="default_org",
                display_name="default organization (autocreated)",
                storage_mb=10,
                storage_threshold_warning_bytes=2_000_000,
                storage_threshold_critical_bytes=1_000_000,
                is_default=True,
                is_public=False,
                user_type=User.Type.ORGANIZATION,
                initial_subscription_status=Subscription.Status.ACTIVE_PAID,
            ),
        ]
    )


def set_subscription(
    users: User | Iterable[User],
    code: str | None = None,
    **kwargs,
):
    if isinstance(users, User):
        users = [users]
    else:
        users = list(users)

    assert len(users), (
        "When iterable, the first argument must contain at least 1 element."
    )

    code = code or f"plan_for_{'_and_'.join([u.username for u in users])}"
    storage_mb = kwargs.get("storage_mb", Plan._meta.get_field("storage_mb").default)
    storage_bytes = storage_mb * 1000 * 1000
    plan = Plan.objects.get_or_create(
        code=code,
        user_type=users[0].type,
        defaults={
            "storage_threshold_warning_bytes": int(storage_bytes * 0.20),
            "storage_threshold_critical_bytes": int(storage_bytes * 0.10),
            "display_name": f"default plan for {code}",
        },
        **kwargs,
    )[0]

    # While technically the `users` could be empty on this line,
    # the earlier assertion guarantees it is not, therefore the
    # following `for` loop will always assign a subscription.
    subscription: Subscription | None = None
    for user in users:
        assert user.type == plan.user_type, (
            f'All users must have the same type "{plan.user_type.value}", but "{user.username}" has "{user.type.value}"'
        )
        subscription = user.useraccount.current_subscription
        subscription.plan = plan
        subscription.purchased_seats = subscription.plan.max_organization_members
        subscription.active_since = timezone.now() - timedelta(days=1)
        subscription.save(update_fields=["plan", "active_since", "purchased_seats"])

    # It is guaranteed that at least one user was provided.
    assert subscription is not None

    return subscription


@contextmanager
def qgz_from_qgs(qgs_path: str | Path, qgz_name: str | None = None) -> Iterator[Path]:
    """Context manager that creates a temporary .qgz file from a .qgs file.

    The .qgz file is placed in a temporary directory that is removed together
    with all its contents when the context exits.

    Args:
        qgs_path: path to the source .qgs file.
        qgz_name: name to use for the .qgz archive (optional).
    """
    qgs_path = Path(qgs_path)

    # Unless a specific `qgz_name` was requested, default to basename of qgs file
    if qgz_name is None:
        qgz_name = qgs_path.with_suffix(".qgz").name

    with tempfile.TemporaryDirectory() as tmpdir:
        qgz_path = Path(tmpdir) / qgz_name
        with zipfile.ZipFile(qgz_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(qgs_path, arcname=qgs_path.name)

        yield qgz_path


def get_random_file(mb: float) -> IO:
    """Helper that returns a file of given size in megabytes"""
    bytes_size = 1000 * int(mb * 1000)
    return io.BytesIO(os.urandom(bytes_size))


class get_named_file_with_size:
    def __init__(self, mb: int) -> None:
        self.bytes_size = 1000 * int(mb * 1000)

    def __enter__(self):
        self.file = tempfile.NamedTemporaryFile("w+b", prefix="qfc_test_tmp_")
        self.file.seek(self.bytes_size - 1)
        self.file.write(b"0")
        self.file.flush()
        self.file.seek(0)

        return self.file

    def __exit__(self, exc_type, exc_value, exc_tb):
        if self.file:
            self.file.close()


def wait_for_project_ok_status(project: Project, wait_s: int = 30):
    """
    Helper that waits for any jobs (worker) of the project to finish.
    NOTE this does not mean the project is updated yet as there
    is some processing to be done and saved to the project in the app.
    So maybe a better name would be 'wait_for_project_jobs_ok_status'.
    """
    jobs = project.jobs.exclude(status__in=[Job.Status.FAILED, Job.Status.FINISHED])

    if not jobs.exists():
        return

    has_pending_jobs = True
    for _ in range(wait_s):
        if not project.jobs.filter(status=Job.Status.PENDING).exists():
            has_pending_jobs = False
            break

        sleep(1)

    if has_pending_jobs:
        fail(f"Still pending jobs after waiting for {wait_s} seconds")

    for _ in range(wait_s):
        try:
            del project.status  # type: ignore
        except AttributeError:
            pass

        project.refresh_from_db()

        if project.status == Project.Status.OK:
            return
        elif project.status == Project.Status.FAILED:
            job = project.jobs.latest("updated_at")

            print("FEEDBACK:", job.feedback)
            print("type1`", job.type)
            print("type2", job)
            print("output:", job.output)

            fail("Waited for ok status, but got failed")

            return

        sleep(1)

    fail(f"Waited for ok status for {wait_s} seconds")


def fail(msg):
    raise AssertionError(msg or "Test case failed")


def get_test_postgis_connection() -> psycopg2.extensions.connection:
    # Temporarily connect to the 'postgres' database so we can recreate the test postgis database
    admin_conn = psycopg2.connect(
        host=settings.TEST_POSTGIS_DB_HOST,
        port=settings.TEST_POSTGIS_DB_PORT,
        dbname="postgres",
        user=settings.TEST_POSTGIS_DB_USER,
        password=settings.TEST_POSTGIS_DB_PASSWORD,
    )
    admin_conn.autocommit = True

    escaped_db_name = psycopg2.extensions.quote_ident(
        settings.TEST_POSTGIS_DB_NAME, scope=admin_conn
    )
    cursor = admin_conn.cursor()
    cursor.execute(f"DROP DATABASE IF EXISTS {escaped_db_name}")
    cursor.execute(f"CREATE DATABASE {escaped_db_name}")
    cursor.close()
    admin_conn.close()

    # Now connect to the newly created test postgis database
    conn = psycopg2.connect(
        host=settings.TEST_POSTGIS_DB_HOST,
        port=settings.TEST_POSTGIS_DB_PORT,
        dbname=settings.TEST_POSTGIS_DB_NAME,
        user=settings.TEST_POSTGIS_DB_USER,
        password=settings.TEST_POSTGIS_DB_PASSWORD,
    )

    cursor = conn.cursor()
    cursor.execute("CREATE EXTENSION postgis")
    cursor.close()

    return conn
