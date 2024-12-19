#!/usr/bin/env python
import argparse
import json
import os
import re
import subprocess

import requests


def get_from_lines(lines, keyword):
    return next(iter(l for l in lines if l.startswith(keyword))).split(keyword)[1].strip()


def scan(interface=None, sudo=False):
    command = []
    if sudo:
        command.append('sudo')
    command.append('iwlist')
    if interface:
        command.append(interface)
    command.append('scan')

    p = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    output = p.communicate()[0].decode().split('Cell')[1:]
    if not output:
        return None

    stations = []
    for data in output:
        lines = [l.strip() for l in data[5:].split('\n')]
        try:
            stations.append({
                'bssid': get_from_lines(lines, 'Address:'),
                'ssid': get_from_lines(lines, 'ESSID:')[1:-1],
                'level': int(get_from_lines(lines, 'Quality=').split('=')[-1][:-4]),
                'frequency': int(float(get_from_lines(lines, 'Frequency:').split(' ')[0]) * 1000)
            })
        except StopIteration:
            pass

    if not stations:
        return []
    return stations


def locate(instance, interface=None, sudo=False, secret=None, api_secret=None, location_timeout=None):
    stations = scan(interface=interface, sudo=sudo)
    if not stations:
        return None

    url = instance
    if url.endswith('/'):
        url = url[0:-1]
    url += '/api/routing/locate/'

    if bool(secret) != bool(api_secret):
        raise ValueError('secret specified but not api_secret, or vice versa')

    json = {
        'stations':  stations,
    }

    if secret and api_secret:
        if not secret.startswith('m:'):
            secret = 'm:' + secret

        json['set_position'] = secret
        json['secret'] = api_secret

        if location_timeout:
            json['timeout'] = int(location_timeout)

    r = requests.post(url, json=json)
    r.raise_for_status()
    return r.json()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description='locate yourself via the c3nav api and optionally update the coordinates of a custom position '
                    'in c3nav')
    parser.add_argument('--instance', '-i', metavar='https://${event}.c3nav.de',
                        required=not bool(os.environ.get('C3NAV_INSTANCE', False)),
                        default=os.environ.get('C3NAV_INSTANCE'),
                        help='The base url of the c3nav instance to use, for example https://36c3.c3nav.de.')
    parser.add_argument('--secret', '-s', default=os.environ.get('C3NAV_SECRET'),
                        help='The secret of a custom position. If specified the custom position belonging to the the '
                             'secret will be updated')
    parser.add_argument('--apisecret', '-a', default=os.environ.get('C3NAV_APISECRET'),
                        help='The api secret of a custom position, needed if you want to update a custom position')
    parser.add_argument('--timeout', '-t', metavar='600', default=os.environ.get('C3NAV_LOCATION_TIMEOUT'), type=int,
                        help='Sets this timeout in seconds on the update to the coordinates of a custom position.')
    parser.add_argument('--sudo', action='store_true', default=bool(os.environ.get('C3NAV_USE_SUDO', False)),
                        help='use sudo, i.e. "sudo iwlist scan"')
    parser.add_argument('--interface', metavar='wlp1s0', default=os.environ.get('C3NAV_SCAN_INTERFACE'),
                        help='Scan use this interface. By default all interfaces are used')
    parser.add_argument('--quiet', '-q', action='store_true', help='don\'t output server response')

    args = parser.parse_args()

    if args.interface and not re.fullmatch(r'[a-zA-Z0-9_-]+', args.interface):
        raise argparse.ArgumentError('invalid character in interface name')

    if args.secret and ' ' in args.secret:
        raise argparse.ArgumentError('invalid character in secret')

    if args.apisecret and ' ' in args.apisecret:
        raise argparse.ArgumentError('invalid character in apisecret')

    if bool(args.secret) != bool(args.apisecret):
        raise argparse.ArgumentError('secret specified but not apisecret, or vice versa')

    location = locate(args.instance, interface=args.interface, sudo=args.sudo, secret=args.secret,
                      api_secret=args.apisecret, location_timeout=args.timeout)

    if location is None:
        # no location found
        if not args.quiet:
            print('no location found')
        exit(1)
    elif not args.quiet:
        print(json.dumps(location, sort_keys=True, indent=4))
