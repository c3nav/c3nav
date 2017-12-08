from c3nav.mapdata.utils.user import get_user_data_lazy


def user_data(request):
    return {
        'user_data': get_user_data_lazy(request)
    }
