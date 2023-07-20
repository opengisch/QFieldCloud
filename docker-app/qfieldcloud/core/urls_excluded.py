def custom_preprocessing_hook(endpoints):
    filtered = []
    for path, path_regex, method, callback in endpoints:
        if path.startswith("/api/"):
            filtered.append((path, path_regex, method, callback))
    return filtered
