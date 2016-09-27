from c3nav.mapdata.models import Package


class Hoster:
    def __init__(self, name, base_url):
        self.name = name
        self.base_url = base_url

    def get_packages(self):
        return Package.objects.filter(home_repo__startswith=self.base_url)

    def _get_session_data(self, request):
        return request.session.setdefault('hosters', {}).setdefault(self.name, {})

    def is_access_granted(self, request):
        return self._get_session_data(request).get('access_granted', False)
