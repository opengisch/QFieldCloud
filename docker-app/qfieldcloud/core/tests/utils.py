import io
import os
from time import sleep
from typing import IO, Iterable, Union

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
    users: Union[User, Iterable[User]],
    code: str = None,
    **kwargs,
):
    if isinstance(users, User):
        users = [users]

    assert len(
        users
    ), "When iterable, the first argument must contain at least 1 element."

    code = code or f"plan_for_{'_and_'.join([u.username for u in users])}"
    plan = Plan.objects.create(
        code=code,
        user_type=users[0].type,
        **kwargs,
    )
    for user in users:
        assert (
            user.type == plan.user_type
        ), 'All users must have the same type "{plan.user_type.value}", but "{user.username}" has "{user.type.value}"'
        subscription = user.useraccount.current_subscription
        subscription.plan = plan
        subscription.save(update_fields=["plan"])

    return subscription


def get_random_file(mb: int) -> IO:
    """Helper that returns a file of given size in megabytes"""
    return io.BytesIO(os.urandom(1000 * int(mb * 1000)))


def wait_for_project_ok_status(project: Project, wait_s: int = 30):
    """
    Helper that waits for any jobs of the project to finish"""
    jobs = Job.objects.filter(project=project).exclude(
        status__in=[Job.Status.FAILED, Job.Status.FINISHED]
    )

    if not jobs.exists():
        return

    has_pending_jobs = True
    for _ in range(wait_s):
        if not Job.objects.filter(project=project, status=Job.Status.PENDING).exists():
            has_pending_jobs = False
            break

        sleep(1)

    if has_pending_jobs:
        fail(f"Still pending jobs after waiting for {wait_s} seconds")

    for _ in range(wait_s):
        project.refresh_from_db()
        if project.status == Project.Status.OK:
            return
        if project.status == Project.Status.FAILED:
            fail("Waited for ok status, but got failed")
            return

        sleep(1)

    fail(f"Waited for ok status for {wait_s} seconds")


def wait_for_has_online_vector_data(project: Project, wait_s: int = 30):
    """
    Helper that waits for ProcessProjectfileJobRun.after_docker_run to finish
    ans asserts there is online vector layers"""
    for _ in range(wait_s):
        project.refresh_from_db()
        if project.has_online_vector_data:
            return True

        sleep(1)

    fail(f"Waited for has_online_vector_data for {wait_s} seconds")


def fail(msg):
    raise AssertionError(msg or "Test case failed")
