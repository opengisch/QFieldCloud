from django.utils.module_loading import import_string


def load_module(name):
    try:
        backend = import_string(name)
        return backend
    except ModuleNotFoundError as e:
        raise ModuleNotFoundError(f'Can not find module path defined "{name}"') from e
    except ImportError as e:
        raise ImportError(f'Can not import backend class defined in "{name}"') from e
