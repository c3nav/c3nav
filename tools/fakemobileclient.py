import http.server
import json
import socketserver
import subprocess
import sys
import time

PORT = int(sys.argv[1]) if sys.argv[1:] else 8042


def get_from_lines(lines, keyword):
    return next(iter(l for l in lines if l.startswith(keyword))).split(keyword)[1].strip()


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
                stations.append({
                    'bssid': get_from_lines(lines, 'Address:'),
                    'ssid': get_from_lines(lines, 'ESSID:')[1:-1],
                    'level': int(get_from_lines(lines, 'Quality=').split('=')[-1][:-4]),
                    'frequency': int(float(get_from_lines(lines, 'Frequency:').split(' ')[0]) * 1000)
                })

            if not stations:
                continue

            break

        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps({'wifi':stations}).encode())
        return True


class ThreadedTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    pass


with ThreadedTCPServer(('127.0.0.1', PORT), FakeMobileClientHandler) as server:
    print('fakemobilelient on 127.0.0.1:%d' % PORT)
    server.serve_forever()
