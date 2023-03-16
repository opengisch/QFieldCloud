from django.contrib.admin.options import IncorrectLookupParameters
import inspect
from django.contrib.admin.views.main import ChangeList
from django.core.paginator import InvalidPage, Paginator
from django.utils.functional import cached_property
from django.utils.inspect import method_has_no_args
from django.db import connection


# class NoCountPaginator(Paginator):
#     @property
#     def count(self):
#         return 999999999 # Some arbitrarily large number,
#                          # so we can still get our page tab.

class LargeTablePaginator(Paginator):
    """
    Overrides the count method to get an estimate instead of actual count when not filtered
    """
    @cached_property
    def count(self):
        """
        Returns the total number of objects, across all pages.
        Changed to use an estimate if the estimate is greater than 10,000
        """
        c = getattr(self.object_list, "count", None)
        if callable(c) and not inspect.isbuiltin(c) and method_has_no_args(c):
            try:
                estimate = 0
                if not self.object_list.query.where:
                    try:
                        cursor = connection.cursor()
                        cursor.execute("SELECT reltuples FROM pg_class WHERE relname = %s",
                            [self.object_list.query.model._meta.db_table])
                        estimate = int(cursor.fetchone()[0])
                    except:
                        pass
                if estimate < 10:
                    return c()
                else:
                    return estimate
            except (AttributeError, TypeError):
                # AttributeError if object_list has no count() method.
                # TypeError if object_list.count() requires arguments
                # (i.e. is of type list).
                pass
        return len(self.object_list)
