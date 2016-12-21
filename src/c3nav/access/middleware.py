import re
from datetime import timedelta

from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from c3nav.access.models import AccessTokenInstance


class AccessTokenMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.c3nav_access_instance = None
        request.c3nav_access_token = None
        request.c3nav_new_access_token = False

        access_cookie = request.COOKIES.get('c3nav_access')
        if access_cookie and re.match(r'^[0-9]+:[a-zA-Z0-9]+$', access_cookie):
            pk, secret = access_cookie.split(':')
            queryset = AccessTokenInstance.objects.filter(Q(access_token__id=int(pk), secret=secret),
                                                          Q(expires__isnull=True) | Q(expires__gt=timezone.now()),
                                                          Q(access_token__expired=False),
                                                          Q(access_token__expires__isnull=True) |
                                                          Q(access_token__expires__gt=timezone.now()))
            access_instance = queryset.select_related('access_token').first()
            if access_instance:
                request.c3nav_access_instance = access_instance
                request.c3nav_access_token = access_instance.access_token
                request.c3nav_access_token.instances.filter(creation_date__lt=access_instance.creation_date).delete()

        response = self.get_response(request)

        if request.c3nav_access_token is not None:
            with transaction.atomic():
                cookie_value = request.c3nav_access_token.new_instance()
                response.set_cookie('c3nav_access', cookie_value, expires=timezone.now() + timedelta(days=30))

                if request.c3nav_new_access_token:
                    request.c3nav_access_token.activated = True
                    request.c3nav_access_token.save()

                    if request.c3nav_access_instance:
                        access_token = request.c3nav_access_instance.access_token
                        access_token.expired = True
                        access_token.save()

        return response
