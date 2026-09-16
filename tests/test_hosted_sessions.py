import http.client
import json
import threading

from openchip.config import Config
from openchip.ui.server import Handler, UIHTTPServer
from openchip.ui.sessions import HostedSessions
from openchip.runtime.workspace import Workspace


def test_http_session_isolation_and_key_retention(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(Handler, "sessions", HostedSessions(Config(), root, 'https://example.test'))
    server = UIHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def request(path, cookie='', body=None, origin=None):
        conn = http.client.HTTPConnection('127.0.0.1', server.server_port)
        headers = {'Host':'example.test', 'Cookie':cookie}
        if origin:
            headers['Origin'] = origin
        conn.request('POST' if body is not None else 'GET', path, json.dumps(body) if body is not None else None, headers)
        response = conn.getresponse()
        raw = response.read()
        result = (response.status, response.getheader('Set-Cookie'), raw)
        conn.close()
        return result

    def check(name, ok):
        assert ok, name

    _, cookie_a, _ = request('/api/runs')
    _, cookie_b, _ = request('/api/runs')
    check('separate opaque HttpOnly Secure cookies', cookie_a != cookie_b and 'HttpOnly' in cookie_a and 'Secure' in cookie_a)
    a,_ = Handler.sessions.select(cookie_a)
    b,_ = Handler.sessions.select(cookie_b)
    a.workspaces.mkdir()
    ws = Workspace(a.workspaces/'private-design')
    ws.init(request='private hardware design request', name='private-design')
    check('owner sees project', b'private-design' in request('/api/runs',cookie_a)[2])
    check('other session cannot list project', request('/api/runs',cookie_b)[2] == b'[]')
    for path in ['/api/runs/private-design', '/api/runs/private-design/bundle.zip', '/api/runs/private-design/artifact?path=request.md', '/api/runs/..%2F..%2Fprivate-design']:
        check('blocked '+path, request(path,cookie_b)[0] == 404)
    for action, body in [('resume', {}),('revise', {'change':'change the private design'})]:
        check('blocked '+action, request('/api/runs/private-design/'+action,cookie_b,body)[0] == 404)
    key='synthetic-private-key-for-session-A'
    settings={'provider':'openai','base_url':'https://api.openai.com/v1','model':'test-model','api_key':key}
    check('settings save',request('/api/settings',cookie_a,settings)[0] == 200)
    check('key belongs to A',a.model_adapter(a.config()).api_key == key)
    check('B has no key',not b.public_settings()['key_present'])
    try:
        b.model_adapter(b.config())
    except ValueError:
        pass
    else:
        raise AssertionError('owner fallback')
    check('private endpoint rejected',request('/api/settings',cookie_a,{**settings,'base_url':'http://127.0.0.1:8000/v1'})[0] == 400)
    check('cross-origin rejected',request('/api/settings',cookie_a,settings,'https://evil.test')[0] == 403)
    Handler.sessions = HostedSessions(Config(),root,'https://example.test')
    check('project survives restart',b'private-design' in request('/api/runs',cookie_a)[2])
    a,_ = Handler.sessions.select(cookie_a)
    check('key forgotten on restart',not a.public_settings()['key_present'])
    check('other session remains isolated after restart',request('/api/runs',cookie_b)[2]==b'[]')
    check('key absent from all persisted files', all(key.encode() not in p.read_bytes() for p in root.rglob('*') if p.is_file()))
    check('activity retained', bool(list(root.rglob('activity.sqlite3'))))
    check('shared logo served',request('/logo.svg',cookie_a)[0]==200)
    server.shutdown()
