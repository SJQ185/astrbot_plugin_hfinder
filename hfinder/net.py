"""网络：普通请求（可走代理）+ 可选的浏览器（Chrome 远程调试口，CDP）。

浏览器只用来做「人能在网页上做的事」：打开站点首页，在页面里发和站点自己网页一样的同源请求。
碰到 Cloudflare 人机验证就停下、报 NeedVerify，让人自己去浏览器里点；不自动点、不改指纹、不接打码服务。
"""

from __future__ import annotations

import http.client
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Mapping

from .settings import FindError, NeedVerify

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
CHALLENGE_TITLE = re.compile(r"(Just a moment|請稍候|请稍候|Attention Required|Checking your browser)", re.I)


class NetError(FindError):
    pass


@dataclass
class Resp:
    status: int
    headers: dict[str, str]
    body: bytes

    def text(self) -> str:
        return self.body.decode("utf-8", "replace")

    def json(self) -> Any:
        try:
            return json.loads(self.body)
        except ValueError as exc:
            raise NetError("对方回的不是 JSON（站点改版了，或者被拦了）") from exc


def looks_challenged(status: int, text: str) -> bool:
    """Cloudflare 验证页 / 拦截页。正常页面也可能挂 /cdn-cgi/ 的统计脚本，所以只看标题和 _cf_chl_opt。"""
    head = text[:20000]
    title = re.search(r"<title>(.*?)</title>", head, re.S | re.I)
    if title and CHALLENGE_TITLE.search(title.group(1)):
        return True
    return "_cf_chl_opt" in head or (status in (403, 503) and "cloudflare" in head.lower())


class Net:
    def __init__(self, proxy: str = "", browser_cdp: str = "") -> None:
        handlers: list[Any] = []
        if proxy.strip():
            handlers.append(urllib.request.ProxyHandler({"http": proxy.strip(), "https": proxy.strip()}))
        self._opener = urllib.request.build_opener(*handlers)
        self._local = urllib.request.build_opener(urllib.request.ProxyHandler({}))   # 本机浏览器口不走代理
        self.cdp = browser_cdp.strip().rstrip("/")

    # ── 普通请求 ─────────────────────────────────────────────────────────────
    def request(self, method: str, url: str, *, data: bytes | None = None, headers: Mapping[str, str] | None = None,
                timeout: float = 40, limit: int = 8 * 1024 * 1024) -> Resp:
        """HTTP 错误照样返回（看 status）；连不上才抛 NetError。"""
        h = {"User-Agent": UA, **(headers or {})}
        req = urllib.request.Request(url, data=data, method=method, headers=h)
        host = urllib.parse.urlsplit(url).netloc
        try:
            with self._opener.open(req, timeout=timeout) as resp:
                body = resp.read(limit + 1)
                want = resp.headers.get("Content-Length")
                if want and want.isdigit() and len(body) < int(want) and len(body) <= limit:
                    raise NetError(f"{host} 没传完就断了")
                return Resp(resp.status, {k.lower(): v for k, v in resp.headers.items()}, body)
        except urllib.error.HTTPError as exc:
            try:
                body = exc.read(300_000)
            except Exception:  # noqa: BLE001
                body = b""
            return Resp(exc.code, {k.lower(): v for k, v in (exc.headers or {}).items()}, body)
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
            raise NetError(f"连不上 {host}（{type(exc).__name__}）") from None

    def get(self, url: str, **kw: Any) -> Resp:
        return self.request("GET", url, **kw)

    def post(self, url: str, data: bytes, **kw: Any) -> Resp:
        return self.request("POST", url, data=data, **kw)

    # ── 浏览器（可选）───────────────────────────────────────────────────────────
    @property
    def has_browser(self) -> bool:
        return bool(self.cdp)

    def _cdp_json(self, path: str, method: str = "GET") -> Any:
        with self._local.open(urllib.request.Request(self.cdp + path, method=method), timeout=10) as resp:
            return json.loads(resp.read())

    def in_page(self, url: str, expression: str, *, site: str, timeout: float = 90) -> Any:
        """在浏览器里新开一个标签页打开 url，等它加载完，在页面里执行 expression（可以是 async），返回结果，关掉标签页。

        页面停在人机验证上 → NeedVerify（让人去浏览器里点）；没配浏览器 / 连不上 → NetError。"""
        if not self.cdp:
            raise NetError("没配浏览器（配置里的 browser_cdp）")
        try:
            from websockets.sync.client import connect
        except ImportError as exc:
            raise NetError("缺 websockets 库（pip install websockets），用不了浏览器") from exc
        try:
            tab = self._cdp_json("/json/new?" + url, "PUT")
        except Exception as exc:  # noqa: BLE001
            raise NetError(f"浏览器连不上（{self.cdp}，{type(exc).__name__}）：确认 Chrome 用 --remote-debugging-port 开着") from exc
        try:
            with connect(tab["webSocketDebuggerUrl"], max_size=128 * 1024 * 1024, open_timeout=10) as ws:
                seq = [0]

                def evaluate(expr: str, wait: float) -> Any:
                    seq[0] += 1
                    ws.send(json.dumps({"id": seq[0], "method": "Runtime.evaluate", "params": {
                        "expression": expr, "awaitPromise": True, "returnByValue": True}}))
                    end = time.time() + wait
                    while time.time() < end:
                        msg = json.loads(ws.recv(timeout=max(0.5, end - time.time())))
                        if msg.get("id") == seq[0]:
                            res = msg.get("result") or {}
                            if "exceptionDetails" in res:
                                raise NetError("浏览器里的脚本出错了")
                            return (res.get("result") or {}).get("value")
                    raise TimeoutError

                want = "{0.scheme}://{0.netloc}".format(urllib.parse.urlsplit(url))
                ready = False
                for _ in range(40):                       # 等加载完，最多 20 秒
                    time.sleep(0.5)
                    try:
                        state = evaluate("location.origin + '|' + document.readyState + '|' + document.title + '|' + "
                                         "((document.body && document.body.innerText) || '').slice(0, 400)", 5) or ""
                    except NetError:
                        raise
                    except Exception:  # noqa: BLE001
                        continue
                    origin, rs, title, body = (str(state).split("|", 3) + ["", "", ""])[:4]
                    if origin != want:                    # 新标签页一开始是 about:blank（readyState 也是 complete），要等它真到了站点
                        continue
                    if CHALLENGE_TITLE.search(title) or "正在进行安全验证" in body or "Enable JavaScript and cookies" in body:
                        continue
                    if rs in ("complete", "interactive"):
                        ready = True
                        break
                if not ready:
                    raise NeedVerify(f"{site} 弹了 Cloudflare 人机验证：请在你配置的那个浏览器里打开 {url} 点一下验证，再搜一次")
                return evaluate(expression, timeout)
        except FindError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise NetError(f"浏览器那边没取到（{type(exc).__name__}）") from exc
        finally:
            try:
                self._local.open(urllib.request.Request(f"{self.cdp}/json/close/{tab['id']}"), timeout=5).read()
            except Exception:  # noqa: BLE001
                pass


def multipart(fields: list[tuple[str, str]], file_field: str, filename: str, payload: bytes,
              ctype: str = "image/jpeg") -> tuple[bytes, str]:
    import uuid
    b = uuid.uuid4().hex
    parts = [f'--{b}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode() for k, v in fields]
    parts.append(f'--{b}\r\nContent-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'
                 f"Content-Type: {ctype}\r\n\r\n".encode() + payload + b"\r\n")
    parts.append(f"--{b}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={b}"
