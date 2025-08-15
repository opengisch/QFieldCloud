import io
import os
import tempfile
from datetime import timedelta
from time import sleep
from typing import IO, Iterable

from django.utils import timezone

from qfieldcloud.core.models import Job, Project, User
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
    Plan.objects.all().delete()
    Plan.objects.bulk_create(
        [
            Plan(
                code="default_user",
                display_name="default user (autocreated)",
                is_default=True,
                is_public=False,
                user_type=User.Type.PERSON,
                initial_subscription_status=Subscription.Status.ACTIVE_PAID,
            ),
            Plan(
                code="default_org",
                display_name="default organization (autocreated)",
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
    users: list[User] = [users] if isinstance(users, User) else users
    assert len(users), (
        "When iterable, the first argument must contain at least 1 element."
    )

    code = code or f"plan_for_{'_and_'.join([u.username for u in users])}"
    plan = Plan.objects.get_or_create(
        code=code,
        user_type=users[0].type,
        **kwargs,
    )[0]
    for user in users:
        assert user.type == plan.user_type, (
            'All users must have the same type "{plan.user_type.value}", but "{user.username}" has "{user.type.value}"'
        )
        subscription: Subscription = user.useraccount.current_subscription
        subscription.plan = plan
        subscription.active_since = timezone.now() - timedelta(days=1)
        subscription.save(update_fields=["plan", "active_since"])

    return subscription


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
            fail("Waited for ok status, but got failed")
            return

        sleep(1)

    fail(f"Waited for ok status for {wait_s} seconds")


def fail(msg):
    raise AssertionError(msg or "Test case failed")
