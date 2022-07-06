import os

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
    if Plan.objects.count() == 0:
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
