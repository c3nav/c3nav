from django.conf import settings


def header_logo(request):
    return {
        'header_logo': settings.HEADER_LOGO_NAME
    }
