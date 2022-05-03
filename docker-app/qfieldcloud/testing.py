from django.conf import settings
from django.test.runner import DiscoverRunner


class QfcTestSuiteRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        settings.IN_TEST_SUITE = True
        super().__init__(*args, **kwargs)
