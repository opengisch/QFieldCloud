import logging
from datetime import datetime

from botocore.exceptions import ClientError
from django.core.files.base import ContentFile
from django.core.files.storage import storages
from django.core.management.base import BaseCommand
from django.db.models import F
from qfieldcloud.core.models import UserAccount

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Migrate avatars from the legacy storage to the `default` storage.
    """

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true", default=False)
        parser.add_argument("--from-storage", type=str, default="legacy_storage")

    def handle(self, *args, **options) -> None:
        useraccounts = (
            UserAccount.objects.select_related("user")
            .filter(
                legacy_avatar_uri__isnull=False,
                avatar__isnull=True,
            )
            .exclude(
                legacy_avatar_uri="",
            )
            .order_by(F("user__last_login").desc(nulls_last=True))
        )

        from_storage: str = options["from_storage"]

        self.stdout.write(
            f"The avatar migration will affect {len(useraccounts)} useraccount(s):"
        )

        yes_no = input("Are you sure you want to continue? [y/n]\n")

        if yes_no != "y":
            self.stdout.write(
                "The files migration will not happen, probably a good choice!"
            )
            return

        from_storage_bucket = storages[from_storage].bucket  # type: ignore

        for useraccount in useraccounts:
            now_str = datetime.now().isoformat(timespec="milliseconds")

            try:
                django_avatar_file = ContentFile(b"", useraccount.legacy_avatar_uri)

                from_storage_bucket.download_fileobj(
                    useraccount.legacy_avatar_uri,
                    django_avatar_file,
                )

                useraccount.avatar = django_avatar_file
                useraccount.save(update_fields=["avatar"])

                self.stdout.write(
                    f'[{now_str}] SUCCESS Migrated avatar for "{useraccount.user.username}" with filename "{useraccount.legacy_avatar_uri}" from "{from_storage}" storage.'
                )
            except ClientError as err:
                if err.response.get("Error", {}).get("Code"):
                    self.stdout.write(
                        f'[{now_str}] ERROR Could not find avatar for "{useraccount.user.username}" with filename "{useraccount.legacy_avatar_uri}" from "{from_storage}" storage!'
                    )
                else:
                    raise err
            except Exception as err:
                self.stdout.write(
                    f'[{now_str}] ERROR Failed migrating avatar for "{useraccount.user.username}" with filename "{useraccount.legacy_avatar_uri}" from "{from_storage}" storage: {err}'
                )
