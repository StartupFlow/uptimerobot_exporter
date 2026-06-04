# FROM https://github.com/hnrd/uptimerobot_exporter/blob/master/exporter.py
# Updated by Martin LEKPA

import argparse
import http.server
import os
import time
import json
import traceback

import threading

import requests

CACHE_TTL = 300
_cache = {'output': None, 'timestamp': 0, 'refreshing': False}


## Monitors
def _fetch_paginated(offset, api_key):
    params = {
        'api_key': api_key,
        'format': 'json',
        'response_times': 1,
        'response_times_limit': 1,
        'custom_uptime_ratios': '1-7-30-90',
        'offset': offset,
    }
    print(f"[DEBUG] getMonitors offset={offset} ...")
    t = time.time()
    resp = requests.post(
        'https://api.uptimerobot.com/v2/getMonitors',
        data=params,
    )
    print(f"[DEBUG] getMonitors offset={offset} -> status={resp.status_code} ({time.time()-t:.2f}s)")
    data = resp.json()
    print(f"[DEBUG] getMonitors offset={offset} -> {len(data.get('monitors', []))} monitors, stat={data.get('stat')}")
    if data.get('stat') != 'ok':
        print(f"[DEBUG] getMonitors ERROR response: {json.dumps(data, indent=2)}")
    return data

def fetch_data(api_key):
    print(f"[DEBUG] fetch_data: starting pagination...")
    monitors = {'monitors':[]}
    offset = 0
    response = _fetch_paginated(offset, api_key)
    for monitor in response['monitors']:
        monitors['monitors'].append(monitor)

    while response['monitors']:
        offset = offset + 50
        print(f"[DEBUG] fetch_data: fetching next page offset={offset}")
        response = _fetch_paginated(offset, api_key)
        for monitor in response['monitors']:
            monitors['monitors'].append(monitor)
    print(f"[DEBUG] fetch_data: done, total={len(monitors['monitors'])} monitors")
    return monitors

def format_prometheus(data):
    result = ''
    for item in data:
        if item.get('status') == 0:
           value = 2
        elif item.get('status') == 1:
           value = 1
        elif item.get('status') == 2:
           value = 0
        else:
           value = 3
        result += 'uptimerobot_status{{c1_name="{}",c2_url="{}",c3_type="{}",c4_sub_type="{}",c5_keyword_type="{}",c6_keyword_value="{}",c7_http_username="{}",c8_port="{}",c9_interval="{}"}} {}\n'.format(
            item.get('friendly_name'),
            item.get('url'),
            item.get('type'),
            item.get('sub_type'),
            item.get('keyword_type'),
            item.get('keyword_value'),
            item.get('http_username'),
            item.get('port'),
            item.get('interval'),
            value,
        )
        if item.get('status', 0) == 2 and item.get('response_times'):
            result += 'uptimerobot_response_time{{name="{}",type="{}",url="{}"}} {}\n'.format(
                item.get('friendly_name'),
                item.get('type'),
                item.get('url'),
                item.get('response_times').pop().get('value'),
            )
        if item.get('custom_uptime_ratio'):
            uptime_ratios = item.get('custom_uptime_ratio').split('-')
            result += 'uptimerobot_uptime_ratio{{name="{}",type="{}",url="{}",uptime_1d="{}",uptime_7d="{}",uptime_30d="{}",uptime_90d="{}"}} 0\n'.format(
                item.get('friendly_name'),
                item.get('type'),
                item.get('url'),
                uptime_ratios[0],
                uptime_ratios[1],
                uptime_ratios[2],
                uptime_ratios[3],
            )
    return result


## getAccountDetails
def fetch_accountdetails(api_key):
    params = {
        'api_key': api_key,
        'format': 'json',
    }
    print(f"[DEBUG] getAccountDetails ...")
    t = time.time()
    req = requests.post(
        'https://api.uptimerobot.com/v2/getAccountDetails',
        data=params,
    )
    data = req.json()
    print(f"[DEBUG] getAccountDetails -> status={req.status_code} stat={data.get('stat')} ({time.time()-t:.2f}s)")
    if data.get('stat') != 'ok':
        print(f"[DEBUG] getAccountDetails ERROR: {json.dumps(data, indent=2)}")
    return data


def format_prometheus_accountdetails(data):
    result = 'uptimerobot_accountdetails{name="%s",monitor_limit="%s",monitor_interval="%s",up_monitors="%s",down_monitors="%s",paused_monitors="%s"} 1\n' %(data['email'],data['monitor_limit'],data['monitor_interval'],data['up_monitors'],data['down_monitors'],data['paused_monitors'])
    return result


## public status pages
def fetch_psp(api_key):
    params = {
        'api_key': api_key,
        'format': 'json',
    }
    print(f"[DEBUG] getPSPs ...")
    t = time.time()
    req = requests.post(
        'https://api.uptimerobot.com/v2/getPSPs',
        data=params,
    )
    data = req.json()
    print(f"[DEBUG] getPSPs -> status={req.status_code} stat={data.get('stat')} ({time.time()-t:.2f}s)")
    if data.get('stat') != 'ok':
        print(f"[DEBUG] getPSPs ERROR: {json.dumps(data, indent=2)}")
    return data


def format_prometheus_psp(data):
  result = ''
  for item in data:
    result += 'uptimerobot_psp{{c1_name="{}",c2_custom_url="{}",c3_standard_url="{}",c4_monitors="{}",c5_sort="{}"}} {}\n'.format(item.get('friendly_name'),item.get('custom_url'),item.get('standard_url'),item.get('monitors'),item.get('sort'),item.get('status'))
  return result




def _refresh_cache(api_key):
    _cache['refreshing'] = True
    try:
        print(f"[DEBUG] _refresh_cache: starting...")
        t = time.time()
        answer = fetch_data(api_key)
        accountdetails = fetch_accountdetails(api_key)
        psp = fetch_psp(api_key)
        output = (
            format_prometheus(answer.get('monitors'))
            + format_prometheus_accountdetails(accountdetails.get('account'))
            + format_prometheus_psp(psp.get('psps'))
        )
        _cache['output'] = output
        _cache['timestamp'] = time.time()
        print(f"[DEBUG] _refresh_cache: done in {time.time()-t:.2f}s ({len(output)} bytes)")
    except Exception as e:
        print(f"[DEBUG] _refresh_cache: ERROR: {e}")
        traceback.print_exc()
    finally:
        _cache['refreshing'] = False


class ReqHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"\n[DEBUG] ====== GET {self.path} from {self.client_address} ======")
        if self.path != '/metrics':
            print(f"[DEBUG] Ignoring non-metrics path: {self.path}")
            self.send_response(404)
            self.end_headers()
            return
        t_total = time.time()
        try:
            cache_age = time.time() - _cache['timestamp']
            if _cache['output'] is None:
                print(f"[DEBUG] No cache yet, fetching synchronously...")
                _refresh_cache(api_key)
            elif cache_age >= CACHE_TTL and not _cache['refreshing']:
                print(f"[DEBUG] Cache expired (age={cache_age:.0f}s), refreshing in background...")
                t = threading.Thread(target=_refresh_cache, args=(api_key,), daemon=True)
                t.start()
            else:
                print(f"[DEBUG] Serving from cache (age={cache_age:.0f}s, refreshing={_cache['refreshing']})")
            output = _cache['output']
            print(f"[DEBUG] Output size: {len(output)} bytes")
            self.send_response(200)
            self.send_header("Content-type", "text/plain")
            self.end_headers()
            self.wfile.write(output.encode('utf-8'))
            print(f"[DEBUG] ====== Response sent in {time.time()-t_total:.2f}s ======\n")
        except BrokenPipeError:
            print(f"[DEBUG] ====== BrokenPipeError after {time.time()-t_total:.2f}s ======\n")
        except Exception as e:
            print(f"[DEBUG] ====== EXCEPTION after {time.time()-t_total:.2f}s ======")
            traceback.print_exc()
            print(f"[DEBUG] ==========================================\n")



if __name__ == '__main__':
    if 'UPTIMEROBOT_API_KEY' in os.environ:
        api_key = os.environ.get('UPTIMEROBOT_API_KEY')
        server_name = os.environ.get('UPTIMEROBOT_SERVER_NAME', '0.0.0.0')
        server_port = int(os.environ.get('UPTIMEROBOT_SERVER_PORT', '9705'))
    else:
        parser = argparse.ArgumentParser(
            description='Export all check results from uptimerobot.txt'
                        'for prometheus scraping.'
        )
        parser.add_argument(
            'apikey',
            help='Your uptimerobot.com API key. See account details.'
        )
        parser.add_argument(
            '--server_name', '-s',
            default='0.0.0.0',
            help='Server address to bind to.'
        )
        parser.add_argument(
            '--server_port', '-p',
            default=9705,
            type=int,
            help='Port to bind to.'
        )
        args = parser.parse_args()
        api_key = args.apikey
        server_name = args.server_name
        server_port = args.server_port

    print(f"[DEBUG] Starting server on {server_name}:{server_port}")
    print(f"[DEBUG] API key: {api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else f"[DEBUG] API key: {api_key}")
    httpd = http.server.HTTPServer((server_name, server_port), ReqHandler)
    print(f"[DEBUG] Server ready, waiting for requests...")
    httpd.serve_forever()
