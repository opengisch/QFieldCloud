from django.core.management.base import BaseCommand
from qfieldcloud.core.utils import get_s3_bucket


class Command(BaseCommand):
    """
    List object storage (S3) files and versions
    """

    def add_arguments(self, parser):
        parser.add_argument("prefix", type=str)
        parser.add_argument(
            "--level",
            type=str,
            default="version",
            help='Level of detail, one of: "version", "file", "summary".  Default is "version".',
        )

    def handle(self, *args, **options):
        prefix = options.get("prefix")
        level = options.get("level")

        assert level in (
            "version",
            "file",
            "summary",
        ), "Level of detail not recognized."

        bucket = get_s3_bucket()

        files_b = 0
        files_count = 0
        files_and_versions_b = 0
        files_and_versions_count = 0
        last_files_count = 0
        for version in bucket.object_versions.filter(Prefix=prefix):
            files_and_versions_count += 1
            files_and_versions_b += version.size or 0

            last_files_count = files_count
            if version.is_latest:
                files_count += 1
                files_b += version.size or 0

            if level in ("version", "file"):
                if level == "version" or version.is_latest:
                    is_latest = "T" if version.is_latest else "F"
                    print(
                        version.id,
                        str(version.last_modified),
                        is_latest,
                        version.e_tag,
                        version.size,
                        version.key,
                        sep="\t",
                    )
            elif level in ("summary",):
                if last_files_count != files_count and files_count % 10000 == 0:
                    print(
                        f"Intermediate results. {files_count} files, {files_b / 1000 / 1000:.2f} MB; {files_and_versions_count} versions, {files_and_versions_b / 1000 / 1000:.5f} MB"
                    )

        print(
            f"Final results. {files_count} files, {files_b / 1000 / 1000:.2f} MB; {files_and_versions_count} versions, {files_and_versions_b / 1000 / 1000:.5f} MB"
        )
