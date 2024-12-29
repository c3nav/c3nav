import http.server
import json
import socketserver
import subprocess
import sys
import time
import struct
import math

import asyncio
from uuid import UUID

from construct import Array, Byte, Const, Int8sl, Int16ub, Struct
from construct.core import ConstError

from collections import OrderedDict

from bleak import BleakScanner
from bleak.backends.device import BLEDevice
from bleak.backends.scanner import AdvertisementData


PORT = int(sys.argv[1]) if sys.argv[1:] else 8042

last_bt_time = {}

ibeacon_format = Struct(
    "type_length" / Const(b"\x02\x15"),
    "uuid" / Array(16, Byte),
    "major" / Int16ub,
    "minor" / Int16ub,
    "power" / Int8sl,
)

def get_from_lines(lines, keyword):
    try: 
        return next(iter(l for l in lines if l.startswith(keyword))).split(keyword)[1].strip()
    except StopIteration:
        return

def calc_distance(txPower, rssi):
    if (rssi == 0):
        return -1.0

    ratio = rssi*1.0/txPower;
    if (ratio < 1.0):
        distance =  math.pow(ratio,10);
    else:
        distance =  (0.89976) * math.pow(ratio,7.7095) + 0.111;
    
    return distance;


async def ble_scan():
    beacons = []

    devices = await BleakScanner.discover(return_adv=True)

    devices = OrderedDict(
        sorted(devices.items(), key=lambda x: x[1][1].rssi, reverse=True)
    )

    for i, (addr, (device, advertisement_data)) in enumerate(devices.items()):
        try:
            apple_data = advertisement_data.manufacturer_data[0x004C]
            ibeacon = ibeacon_format.parse(apple_data)
            uuid = UUID(bytes=bytes(ibeacon.uuid))

            now = time.time()
            if str(uuid) in last_bt_time:
                lastTime = last_bt_time[str(uuid)]
            else:
                lastTime = now
                        
            last_bt_time[str(uuid)] = now
            beacons.append({'uuid': str(uuid), 'major': ibeacon.major, 'minor': ibeacon.minor, 'distance': calc_distance(ibeacon.power, advertisement_data.rssi), 'last_seen_ago': lastTime })
        except KeyError:
            # Apple company ID (0x004c) not found
            pass
        except ConstError:
            # No iBeacon (type 0x02 and length 0x15)
            pass
    
    return beacons

def async_to_sync(awaitable):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(awaitable)

class FakeMobileClientHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        """Serve a GET request."""
        if self.path != '/scan':
            self.send_error(404, explain='Look at /scan')
            return

        while True:
            p = subprocess.Popen(['iwlist', 'scan'], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            output = p.communicate()[0].decode().split('Cell')[1:]
            if not output:
                print('scan failed, try again…')
                time.sleep(0.2)
                continue

            stations = []
            for data in output:
                lines = [l.strip() for l in data[5:].split('\n')]
                
                station = {
                    'bssid': get_from_lines(lines, 'Address:'),
                    'ssid': get_from_lines(lines, 'ESSID:')[1:-1],
                    'level': int(get_from_lines(lines, 'Quality=').split('=')[-1][:-4]),
                    'frequency': int(float(get_from_lines(lines, 'Frequency:').split(' ')[0]) * 1000)
                }
                
                ap_name = get_from_lines(lines, 'IE: Unknown: DD0B000B86010300')
                if (ap_name and ap_name != ""):
                    station['ap_name'] = bytearray.fromhex(ap_name).decode()
                
                stations.append(station)

            if not stations:
                continue

            break

        beacons = async_to_sync(ble_scan())

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'wifi':stations, 'ibeacon':beacons}).encode())
        return True


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


with ThreadedTCPServer(('127.0.0.1', PORT), FakeMobileClientHandler) as server:
    print('fakemobilelient on 127.0.0.1:%d' % PORT)
    server.serve_forever()
