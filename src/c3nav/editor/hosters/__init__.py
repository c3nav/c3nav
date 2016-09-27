from django.conf import settings
from c3nav.editor.hosters.github import GithubHoster  # noqa
from c3nav.editor.hosters.gitlab import GitlabHoster  # noqa

from collections import OrderedDict


hosters = {}


def init_hosters():
    global hosters
    hosters = OrderedDict((name, create_hoster(name=name, **data)) for name, data in settings.EDITOR_HOSTERS.items())


def create_hoster(api, **kwargs):
    if api == 'github':
        return GithubHoster(**kwargs)
    elif api == 'gitlab':
        return GitlabHoster(**kwargs)
    else:
        raise ValueError('Unknown hoster API: %s' % api)


def get_hoster_for_package(package):
    for name, hoster in hosters.items():
        if package.home_repo.startswith(hoster.base_url):
            return hoster
    return None
