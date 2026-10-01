"""Local productivity dashboard; Python 3.10+, no third-party dependencies."""
import json
import sqlite3
import urllib.request
import urllib.error
import uuid
import webbrowser
import threading
import argparse
from datetime import datetime, timezone
from pathlib import Path
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

ROOT = Path(__file__).resolve().parent
DB = ROOT / 'data.sqlite3'
AW = 'http://127.0.0.1:5600/api/0'

class ClosingConnection(sqlite3.Connection):
    def __exit__(self, *args):
        try:
            return super().__exit__(*args)
        finally:
            self.close()

def connect():
    db = sqlite3.connect(DB, factory=ClosingConnection)
    db.execute('CREATE TABLE IF NOT EXISTS entries (id TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, payload TEXT NOT NULL)')
    return db

def aw(path, payload=None):
    req = urllib.request.Request(AW + path, data=None if payload is None else json.dumps(payload).encode(),
                                 headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(req, timeout=12) as res:
        return json.load(res)

def valid_entry(data):
    activity = str(data.get('activity', '')).strip()
    if not activity or len(activity) > 120:
        raise ValueError('Enter an activity name of 1–120 characters.')
    start = datetime.fromisoformat(data['start'].replace('Z', '+00:00'))
    end = datetime.fromisoformat(data['end'].replace('Z', '+00:00'))
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError('Dates must include a timezone.')
    if not 0 < (end-start).total_seconds() <= 86400:
        raise ValueError('An entry must last between one second and 24 hours.')
    if end > datetime.now(timezone.utc):
        raise ValueError('Activities cannot end in the future.')
    return {'id': str(uuid.uuid4()), 'activity': activity, 'start': start.isoformat(),
            'end': end.isoformat(), 'notes': str(data.get('notes', ''))[:1000], 'source': 'manual'}

class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT / 'static'), **kwargs)

    def log_message(self, *args):
        pass

    def trusted(self):
        return self.headers.get('Host') in (f'127.0.0.1:{self.server.server_port}', f'localhost:{self.server.server_port}')

    def respond(self, data, code=200):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if not self.trusted():
            return self.respond({'error': 'Invalid host'}, 403)
        url = urlparse(self.path)
        try:
            if url.path == '/api/state':
                with connect() as db:
                    entries = [json.loads(row[0]) for row in db.execute('SELECT payload FROM entries')]
                    settings = {row[0]: json.loads(row[1]) for row in db.execute('SELECT key,payload FROM settings')}
                return self.respond({'entries': entries, 'settings': settings})
            if url.path == '/api/automatic':
                params = parse_qs(url.query)
                start, end = params['start'][0], params['end'][0]
                a, b = datetime.fromisoformat(start.replace('Z', '+00:00')), datetime.fromisoformat(end.replace('Z', '+00:00'))
                if not 0 < (b-a).total_seconds() <= 15*86400:
                    raise ValueError('Request up to 15 days at a time.')
                buckets = aw('/buckets/')
                windows = [v for v in buckets.values() if v.get('type') == 'currentwindow' and not v['id'].startswith('aw-watcher-android')]
                hosts = list(dict.fromkeys(v.get('hostname', '') for v in windows))
                host = params.get('host', [''])[0] or (hosts[0] if hosts else '')
                window = next((v for v in windows if v.get('hostname') == host), None)
                afk = next((v for v in buckets.values() if v.get('type') == 'afkstatus' and v.get('hostname') == host), None)
                if not window or not afk:
                    return self.respond({'connected': True, 'events': [], 'hosts': hosts, 'host': host,
                                         'message': 'Start ActivityWatch’s window and AFK watchers to record active computer time.'})
                query = f'''events = flood(query_bucket({json.dumps(window['id'])}));
active = flood(query_bucket({json.dumps(afk['id'])}));
active = filter_keyvals(active, "status", ["not-afk"]);
RETURN = filter_period_intersect(events, active);'''
                result = aw('/query/', {'timeperiods': [start+'/'+end], 'query': [query]})
                events = [{'id': 'aw-'+str(i), 'start': e['timestamp'], 'end':
                           datetime.fromtimestamp(datetime.fromisoformat(e['timestamp'].replace('Z', '+00:00')).timestamp()+e['duration'], timezone.utc).isoformat(),
                           'activity': e.get('data', {}).get('app') or 'Unknown application', 'source': 'automatic', 'notes': ''}
                          for i, e in enumerate(result[0]) if e.get('duration', 0) > 0]
                return self.respond({'connected': True, 'events': events, 'hosts': hosts, 'host': host, 'message': ''})
            if url.path.startswith('/api/'):
                return self.respond({'error': 'Not found'}, 404)
            return super().do_GET()
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            return self.respond({'connected': False, 'events': [], 'hosts': [], 'message':
                'ActivityWatch is unavailable. Open ActivityWatch on this computer, then refresh. Manual logging still works.'})
        except Exception as exc:
            return self.respond({'error': str(exc)}, 400)

    def do_POST(self):
        if not self.trusted() or self.headers.get('Origin') not in (None, f'http://127.0.0.1:{self.server.server_port}', f'http://localhost:{self.server.server_port}'):
            return self.respond({'error': 'Invalid origin'}, 403)
        if not self.headers.get('Content-Type', '').startswith('application/json'):
            return self.respond({'error': 'JSON required'}, 415)
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length < 65536:
                raise ValueError('Invalid request size')
            data = json.loads(self.rfile.read(length))
            with connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if self.path in ('/api/entries', '/api/timer/stop'):
                    if self.path == '/api/timer/stop':
                        row = db.execute("SELECT payload FROM settings WHERE key='timer'").fetchone()
                        timer = json.loads(row[0]) if row else None
                        if not timer:
                            raise ValueError('No timer is running.')
                        data = {**timer, 'end': datetime.now(timezone.utc).isoformat()}
                    entry = valid_entry(data)
                    for (raw,) in db.execute('SELECT payload FROM entries'):
                        old = json.loads(raw)
                        if datetime.fromisoformat(entry['start']) < datetime.fromisoformat(old['end']) and datetime.fromisoformat(entry['end']) > datetime.fromisoformat(old['start']):
                            raise ValueError('This overlaps another manual entry. Delete that entry first or choose another time.')
                    db.execute('INSERT INTO entries VALUES (?,?)', (entry['id'], json.dumps(entry)))
                    if self.path == '/api/timer/stop':
                        db.execute("DELETE FROM settings WHERE key='timer'")
                    db.commit()
                    return self.respond(entry, 201)
                if self.path == '/api/delete':
                    db.execute('DELETE FROM entries WHERE id=?', (str(data['id']),))
                    db.commit()
                    return self.respond({'ok': True})
                if self.path == '/api/settings':
                    key = data['key']
                    if key not in ('focus', 'timer'):
                        raise ValueError('Unknown setting')
                    if key == 'focus' and (not isinstance(data['value'], list) or not all(isinstance(x, str) and len(x) <= 200 for x in data['value'])):
                        raise ValueError('Invalid focus activities')
                    if key == 'timer' and data['value'] is not None:
                        current = db.execute("SELECT payload FROM settings WHERE key='timer'").fetchone()
                        if current and json.loads(current[0]):
                            raise ValueError('A timer is already running. Refresh to see it.')
                        if not str(data['value'].get('activity', '')).strip() or len(data['value']['activity']) > 120:
                            raise ValueError('Enter an activity name of 1–120 characters.')
                        data['value']['start'] = datetime.now(timezone.utc).isoformat()
                    db.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key, json.dumps(data['value'])))
                    db.commit()
                    return self.respond({'ok': True})
                return self.respond({'error': 'Not found'}, 404)
        except Exception as exc:
            return self.respond({'error': str(exc)}, 400)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--port', type=int, default=8765)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    connect().close()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    print(f'Productivity dashboard: http://127.0.0.1:{args.port}', flush=True)
    if not args.no_browser:
        threading.Timer(.5, lambda: webbrowser.open(f'http://127.0.0.1:{args.port}')).start()
    server.serve_forever()
