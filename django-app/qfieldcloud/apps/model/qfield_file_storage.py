from django.core.files.storage import FileSystemStorage
from django.conf import settings
from django.utils.functional import cached_property


class QFieldStorage(FileSystemStorage):

    def _save(self, name, content):
        if self.exists(name):
            self.delete(name)
        return super()._save(name, content)

    def get_available_name(self, name, max_length=None):
        return name

    @cached_property
    def base_location(self):
        return self._value_or_setting(self._location, settings.PROJECTS_ROOT)
