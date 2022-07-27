import io
import os
from typing import IO

from qfieldcloud.subscription.models import Plan


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
                user_type=Plan.UserType.USER,
            ),
            Plan(
                code="default_org",
                display_name="default organization (autocreated)",
                is_default=True,
                is_public=False,
                user_type=Plan.UserType.ORGANIZATION,
            ),
        ]
    )


def get_random_file(mb: int) -> IO:
    """Helper that returns a file of given size in megabytes"""
    return io.BytesIO(os.urandom(1000 * int(mb * 1000)))
