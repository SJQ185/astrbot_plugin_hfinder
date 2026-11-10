"""soutubot.moe（搜图 Bot 酱）：本子内页 / 残页 / 盖了字的截图 → 哪一本、第几页。局部截图找本子目前最准。

它前面挡着 Cloudflare，而且只收它自己网页发出的请求，所以只能借一个真浏览器：
在浏览器里打开 soutubot.moe 首页，在页面里像它自己的网页那样 POST /api/search。
弹了人机验证就停下，让人去浏览器里点；不绕。没配浏览器就用不了（会提示手动去网页上传）。
有每日次数和频率限制，用完了它会直接说。
"""

from __future__ import annotations

import base64
import io
import json
from typing import Any

from .net import Net
from .settings import FindError, NeedVerify

HOME = "https://soutubot.moe/"
GOOD_SCORE = 45.0                 # 常规模式 ≥45 可信；实测真命中 70 多，无关的 25 以下

_JS = """(async () => {
  try {
    const bin = atob(%s);
    const arr = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) arr[i] = bin.charCodeAt(i);
    const fd = new FormData();
    fd.append('file', new Blob([arr], {type: 'image/jpeg'}), 'image.jpg');
    fd.append('factor', '1.2');
    const resp = await fetch('/api/search', {method: 'POST', body: fd, headers: {'Accept': 'application/json'}});
    return JSON.stringify({ok: true, status: resp.status, text: await resp.text()});
  } catch (e) {
    return JSON.stringify({ok: false, error: String(e && e.message || e)});
  }
})()"""


def _jpeg(image: bytes) -> bytes:
    """它的网页会把图压到宽 ≤2000、≤5MB 的 JPEG，照做。"""
    from PIL import Image
    im = Image.open(io.BytesIO(image))
    im.load()
    if im.width > 2000:
        im = im.resize((2000, max(1, round(im.height * 2000 / im.width))))
    buf = io.BytesIO()
    im.convert("RGB").save(buf, "JPEG", quality=90)
    return buf.getvalue()


def search(net: Net, image: bytes) -> list[dict[str, Any]]:
    """→ [{score, source, id, page, title, url, thumb}]，按分数从高到低（只留 ≥45 分的）。"""
    if not net.has_browser:
        raise FindError("soutubot 要借浏览器才能用（配置里没填 browser_cdp）")
    payload = base64.b64encode(_jpeg(image)).decode()
    raw = net.in_page(HOME, _JS % json.dumps(payload), site="soutubot", timeout=90)
    try:
        res = json.loads(str(raw or "{}"))
    except ValueError as exc:
        raise FindError("soutubot 回的东西看不懂") from exc
    if not res.get("ok"):
        raise FindError(f"soutubot 请求没发出去：{str(res.get('error') or '')[:80]}")
    text = str(res.get("text") or "").strip()
    if not text.startswith("{"):
        raise NeedVerify("soutubot 弹了 Cloudflare 人机验证：请在你配置的那个浏览器里打开 https://soutubot.moe/ 点一下验证，再搜一次")
    data = json.loads(text)
    if data.get("detail"):
        raise FindError(f"soutubot：{str(data['detail'])[:80]}")            # 今日次数用完 / 太频繁 等，原样转述
    return parse(data)


def parse(data: dict[str, Any]) -> list[dict[str, Any]]:
    """结果不按分数排（实测命中的排在第 50 多条），自己排；有的结果没有 path_segments，就读外层。"""
    out = []
    for row in data.get("results") or []:
        if not isinstance(row, dict):
            continue
        try:
            score = float(row.get("score") or 0)
        except (TypeError, ValueError):
            continue
        if score < GOOD_SCORE:
            continue
        for seg in row.get("path_segments") or [row]:
            if not isinstance(seg, dict):
                continue
            meta = seg.get("metadata") or row.get("metadata") or {}
            t = meta.get("title") or {}
            title = (t.get("primary") or t.get("japanese_or_alias") or t.get("japanese") or t.get("english")
                     or t.get("pretty") or "") if isinstance(t, dict) else str(t)
            links = seg.get("links") or row.get("links") or {}
            source = str(seg.get("source_key") or row.get("source_key") or "").strip().lower()
            ext_id = str(seg.get("external_id") or row.get("external_id") or "").strip()
            page_url = str(links.get("page_url") or links.get("gallery_url") or "")
            out.append({"score": round(score, 1), "source": source, "id": ext_id,
                        "page": seg.get("page_no", row.get("page_no")), "title": str(title or ""),
                        "url": str(links.get("source_url") or page_url), "page_url": page_url,
                        "tags": [str(x) for x in meta.get("tags") or [] if isinstance(x, (str, int))],
                        "thumb": str(links.get("thumbnail_url") or "")})
    return sorted(out, key=lambda x: -x["score"])
