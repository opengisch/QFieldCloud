from django.test.runner import DiscoverRunner

# Whether we are currently running tests
IN_TEST_SUITE = False


class QfcTestSuiteRunner(DiscoverRunner):
    def __init__(self, *args, **kwargs):
        global IN_TEST_SUITE
        IN_TEST_SUITE = True
        super().__init__(*args, **kwargs)
