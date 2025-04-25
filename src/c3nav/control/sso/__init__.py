_sso_services = None


def get_sso_services() -> dict[str, str]:
    global _sso_services
    from social_core.backends.utils import load_backends
    from social_django.utils import load_strategy

    if _sso_services is None:
        _sso_services = dict()
        for backend in load_backends(load_strategy().get_backends()).values():
            _sso_services[backend.name] = getattr(backend, 'verbose_name', backend.name.replace('-', ' ').capitalize())

    return _sso_services


