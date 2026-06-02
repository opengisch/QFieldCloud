from django.conf import settings


def expose_spectacular_endpoints(endpoints: list[tuple], **kwargs) -> list[tuple]:
    """Filter out admin paths from the list of endpoints to be included in the OpenAPI schema."""
    admin_prefix = f"/{settings.QFIELDCLOUD_ADMIN_URI}"

    exposed_paths = []

    for endpoint_path, endpoint_path_regex, method, callback in endpoints:
        if not endpoint_path.startswith(admin_prefix):
            exposed_paths.append((endpoint_path, endpoint_path_regex, method, callback))

    return exposed_paths
