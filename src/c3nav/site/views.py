from django.shortcuts import redirect, render

from c3nav.mapdata.models.locations import get_location


def main(request, origin=None, destination=None):
    do_redirect = False

    if origin:
        origin_obj = get_location(request, origin)
        if origin_obj.name != origin:
            do_redirect = True
        origin = origin_obj

    if destination:
        destination_obj = get_location(request, destination)
        if destination_obj.name != destination:
            do_redirect = True
        destination = destination_obj

    if do_redirect:
        new_url = '/'
        if origin:
            new_url += origin.name+'/'
            if destination:
                new_url += destination.name + '/'
        elif destination:
            new_url += '_/' + destination.name + '/'

        redirect(new_url)

    return render(request, 'site/main.html', {
        'origin': origin,
        'destination': destination
    })
