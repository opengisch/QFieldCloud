import configparser
import io

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

PGSERVICE_SECRET_NAME_PREFIX = "PG_SERVICE_"


def validate_pg_service_conf(value: str) -> None:
    """Checks if a string is a valid `pg_service.conf` file contents, otherwise throws a `ValueError`"""
    try:
        buffer = io.StringIO(value)
        config = configparser.ConfigParser()
        config.read_file(buffer)

        if len(config.sections()) != 1:
            raise ValidationError(
                _("The `.pg_service.conf` must have exactly one service definition.")
            )
    except ValidationError as err:
        raise err
    except Exception:
        raise ValidationError(_("Failed to parse the `.pg_service.conf` file."))
