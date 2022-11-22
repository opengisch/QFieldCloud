import io
import os
from typing import IO, Iterable, Union

from qfieldcloud.core.models import User
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
        subscription = user.useraccount.active_subscription
        subscription.plan = plan
        subscription.save(update_fields=["plan"])

    return subscription


def get_random_file(mb: int) -> IO:
    """Helper that returns a file of given size in megabytes"""
    return io.BytesIO(os.urandom(1000 * int(mb * 1000)))
