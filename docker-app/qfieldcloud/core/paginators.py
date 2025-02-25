import inspect

from django.conf import settings
from django.core.paginator import Paginator
from django.db import connection
from django.utils.functional import cached_property
from django.utils.inspect import method_has_no_args


class LargeTablePaginator(Paginator):
    """
    Only for Postgres:
    Overrides the count method to get an estimate instead of actual count when not filtered
    inspired by: https://djangosnippets.org/snippets/2855/
    """

    @cached_property
    def count(self):
        """
        Returns the total number of objects, across all pages.
        Changed to use an estimate if the estimate is greater than QFIELDCLOUD_ADMIN_EXACT_COUNT_LIMIT
        """
        c = getattr(self.object_list, "count", None)
        if callable(c) and not inspect.isbuiltin(c) and method_has_no_args(c):
            estimate = 0
            if not self.object_list.query.where:
                cursor = connection.cursor()
                cursor.execute(
                    "SELECT reltuples::int FROM pg_class WHERE relname = %s",
                    [self.object_list.query.model._meta.db_table],
                )
                estimate = cursor.fetchone()[0]

            if estimate < settings.QFIELDCLOUD_ADMIN_EXACT_COUNT_LIMIT:
                return c()
            else:
                return estimate

        return len(self.object_list)
