from django.conf import settings
from django.test.runner import DiscoverRunner


class QfcTestSuiteRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        settings.IN_TEST_SUITE = True
        settings.QFIELDCLOUD_MINIMUM_RANGE_HEADER_LENGTH = 1
        super().__init__(*args, **kwargs)
