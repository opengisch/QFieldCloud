import copy

from django.conf import settings
from django.test.runner import DiscoverRunner
from django.test.utils import override_settings


class QfcTestSuiteRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        settings.IN_TEST_SUITE = True
        super().__init__(*args, **kwargs)

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)

        # Key prefix that keeps caches from overwriting the app's cached values
        caches_config = copy.deepcopy(settings.CACHES)
        caches_config["default"]["KEY_PREFIX"] = "test"
        self.caches_override = override_settings(CACHES=caches_config)
        self.caches_override.enable()

    def teardown_test_environment(self, **kwargs):
        self.caches_override.disable()
        super().teardown_test_environment(**kwargs)
