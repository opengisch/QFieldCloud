from constance.backends.database import DatabaseBackend as BaseDatabaseBackend


class DatabaseBackend(BaseDatabaseBackend):
    """
    Fix for https://github.com/jazzband/django-constance/issues/348
    Overrides the `get` method to remove silencing of database failures.
    Such errors would otherwise result in unwanted resetting of parameters
    to default values.

    Source: https://github.com/jazzband/django-constance/issues/348#issuecomment-676831598
    """

    def get(self, key):
        key = self.add_prefix(key)
        if self._cache:
            value = self._cache.get(key)
            if value is None:
                self.autofill()
                value = self._cache.get(key)
        else:
            value = None
        if value is None:
            try:
                value = self._model._default_manager.get(key=key).value

                if self._cache:
                    self._cache.add(key, value)
            except self._model.DoesNotExist:  # Only catch DoesNotExist exceptions here
                pass
        return value
