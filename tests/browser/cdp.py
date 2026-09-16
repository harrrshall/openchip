"""Minimal Chrome DevTools Protocol driver: stdlib only, enough to measure layout and press keys."""
import base64, hashlib, json, os, socket, struct, subprocess, time, urllib.request

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


class WS:
    def __init__(self, url):
        _, _, rest = url.partition("://")
        hostport, _, path = rest.partition("/")
        host, _, port = hostport.partition(":")
        self.sock = socket.create_connection((host, int(port or 80)), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        req = (f"GET /{path} HTTP/1.1\r\nHost: {hostport}\r\nUpgrade: websocket\r\n"
               f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n")
        self.sock.sendall(req.encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(4096)
        accept = base64.b64encode(hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()).digest()).decode()
        assert accept.encode() in buf, buf[:200]
        self.buf = buf.split(b"\r\n\r\n", 1)[1]

    def send(self, obj):
        data = json.dumps(obj).encode()
        header = bytearray([0x81])
        mask = os.urandom(4)
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < (1 << 16):
            header.append(0x80 | 126); header += struct.pack(">H", n)
        else:
            header.append(0x80 | 127); header += struct.pack(">Q", n)
        header += mask
        self.sock.sendall(bytes(header) + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise IOError("socket closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def recv(self):
        b1, b2 = self._read(2)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack(">H", self._read(2))[0]
        elif length == 127:
            length = struct.unpack(">Q", self._read(8))[0]
        payload = self._read(length)
        return json.loads(payload.decode())


class Browser:
    def __init__(self, port=9333, width=1440, height=1000, dark=False):
        self.port = port
        self.profile = f"/tmp/cdp-profile-{port}"
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars",
             f"--remote-debugging-port={port}", f"--user-data-dir={self.profile}",
             f"--window-size={width},{height}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        url = None
        for _ in range(60):
            try:
                pages = json.load(urllib.request.urlopen(f"http://127.0.0.1:{port}/json"))
                url = [p for p in pages if p["type"] == "page"][0]["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.5)
        assert url, "chrome did not start"
        self.ws = WS(url)
        self.id = 0
        self.console = []
        for d in ("Page", "Runtime", "Log"):
            self.cmd(f"{d}.enable")
        self.cmd("Emulation.setEmulatedMedia", {"features": [{"name": "prefers-color-scheme", "value": "dark" if dark else "light"}]})

    def cmd(self, method, params=None, timeout=45):
        self.id += 1
        mid = self.id
        self.ws.send({"id": mid, "method": method, "params": params or {}})
        deadline = time.time() + timeout
        while time.time() < deadline:
            msg = self.ws.recv()
            if msg.get("method") in ("Runtime.consoleAPICalled", "Log.entryAdded", "Runtime.exceptionThrown"):
                self.console.append(msg)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})
        raise TimeoutError(method)

    def goto(self, url, settle=1.6):
        self.cmd("Page.navigate", {"url": url})
        time.sleep(settle)

    def js(self, expr, awaitp=False):
        r = self.cmd("Runtime.evaluate", {"expression": expr, "returnByValue": True, "awaitPromise": awaitp})
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("text", "js error") + " :: " + expr[:120])
        return r["result"].get("value")

    def key(self, key, code=None, text=None, mods=0, vk=None):
        base = {"modifiers": mods, "key": key, "code": code or key, "windowsVirtualKeyCode": vk or 0,
                "nativeVirtualKeyCode": vk or 0}
        self.cmd("Input.dispatchKeyEvent", dict(base, type="keyDown", text=text or ""))
        self.cmd("Input.dispatchKeyEvent", dict(base, type="keyUp"))
        time.sleep(0.08)

    def type(self, text):
        for ch in text:
            if ch == "\n":
                self.key("Enter", "Enter", "\r", vk=13)
            else:
                self.cmd("Input.dispatchKeyEvent", {"type": "keyDown", "text": ch, "key": ch, "modifiers": 0})
                self.cmd("Input.dispatchKeyEvent", {"type": "keyUp", "key": ch, "modifiers": 0})
        time.sleep(0.15)

    def click(self, selector):
        box = self.js(f"(()=>{{const n=document.querySelector({json.dumps(selector)}); if(!n) return null;"
                      f"const r=n.getBoundingClientRect(); return [r.x+r.width/2, r.y+r.height/2];}})()")
        assert box, f"no element {selector}"
        for t in ("mousePressed", "mouseReleased"):
            self.cmd("Input.dispatchMouseEvent", {"type": t, "x": box[0], "y": box[1], "button": "left",
                                                  "clickCount": 1, "buttons": 1 if t == "mousePressed" else 0})
        time.sleep(0.25)

    def resize(self, w, h):
        self.cmd("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 1, "mobile": w < 700})
        time.sleep(0.5)

    def shot(self, path, full=False):
        r = self.cmd("Page.captureScreenshot", {"captureBeyondViewport": full})
        open(path, "wb").write(base64.b64decode(r["data"]))

    def errors(self):
        out = []
        for m in self.console:
            if m.get("method") == "Runtime.exceptionThrown":
                out.append(m["params"]["exceptionDetails"].get("text", "exception"))
            elif m.get("method") == "Log.entryAdded" and m["params"]["entry"].get("level") == "error":
                out.append(m["params"]["entry"].get("text", ""))
            elif m.get("method") == "Runtime.consoleAPICalled" and m["params"].get("type") == "error":
                out.append(" ".join(str(a.get("value", "")) for a in m["params"].get("args", [])))
        return [e for e in out if "favicon" not in e.lower()]

    def close(self):
        try:
            self.proc.terminate()
        except Exception:
            pass
