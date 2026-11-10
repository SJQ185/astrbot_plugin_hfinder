"""E-Hentai / ExHentai：按关键词 / 标签搜、看排行榜、取本子资料（gdata）、站内以图搜本。

不填 cookie 走表站 e-hentai.org；三个 cookie 都填了走里站 exhentai.org（结果更全）。
站上的规矩：两次请求至少隔 3 秒，连着 4 次以后停 5 秒。只搜、只回资料，不读页、不下载。
"""

from __future__ import annotations

import difflib
import html
import json
import re
import threading
import time
import urllib.parse
from typing import Any, Mapping

from .net import Net, multipart
from .redline import Filter
from .settings import FindError

SITES = {
    "exhentai": {"base": "https://exhentai.org", "api": "https://exhentai.org/api.php",
                 "upload": "https://upld.exhentai.org/upld/image_lookup.php"},
    "e-hentai": {"base": "https://e-hentai.org", "api": "https://api.e-hentai.org/api.php",
                 "upload": "https://upld.e-hentai.org/image_lookup.php"},
}
COOKIE_KEYS = ("ipb_member_id", "ipb_pass_hash", "igneous")
GALLERY_RE = re.compile(r"https?://(?:e-hentai|exhentai)\.org/g/(\d+)/([0-9a-f]{10})")
BRACKETS_RE = re.compile(r"[\(（][^\(\)（）\[\]【】]*[\)）]|\[[^\[\]\(\)（）]*\]|【[^【】]*】")
INTERVAL_S = 3.0
CATEGORY_BITS = {"Misc": 1, "Doujinshi": 2, "Manga": 4, "Artist CG": 8, "Game CG": 16, "Image Set": 32,
                 "Cosplay": 64, "Asian Porn": 128, "Non-H": 256, "Western": 512}
NOT_DOUJIN = CATEGORY_BITS["Western"] | CATEGORY_BITS["Cosplay"] | CATEGORY_BITS["Asian Porn"] | CATEGORY_BITS["Image Set"]
TOPLIST = {"day": 15, "month": 13, "year": 12, "all": 11}
RANKING_LABELS = {"popular": "当下热门", "day": "昨日榜", "month": "上月榜", "year": "去年榜", "all": "历史总榜"}

ZH_TAG_ALIASES: dict[str, str] = {
    "肛交": "female:anal", "走后门": "female:anal", "后庭": "female:anal", "尿道": 'female:"urethra insertion"',
    "丝袜": "female:stockings", "连裤袜": "female:pantyhose", "裤袜": "female:pantyhose", "足交": "female:footjob",
    "口交": "female:blowjob", "乳交": "female:paizuri", "触手": "female:tentacles", "催眠": 'female:"mind control"',
    "常识改变": 'female:"mind control"', "调教": "female:bdsm", "捆绑": "female:bondage", "内射": "female:nakadashi",
    "中出": "female:nakadashi", "灌肠": "female:enema", "放尿": "female:urination", "双马尾": "female:twintails",
    "女仆": "female:maid", "修女": "female:nun", "巫女": "female:miko", "魔法少女": 'female:"magical girl"',
    "百合": "female:yuri", "伪娘": "male:tomgirl", "纯爱": "other:vanilla", "牛头人": "female:netorare",
    "ntr": "female:netorare", "人妻": "female:milf", "熟女": "female:milf", "阿黑颜": "female:ahegao",
    "精灵": "female:elf", "兽耳": "female:kemonomimi", "猫耳": "female:catgirl", "魅魔": "female:succubus",
    "兔女郎": 'female:"bunny girl"', "泳装": "female:swimsuit", "眼罩": "female:blindfold", "拉珠": 'female:"anal beads"',
    "扩张": "female:gaping", "全彩": "other:\"full color\"", "无修正": "other:uncensored", "无码": "other:uncensored",
    "中文": "language:chinese", "汉化": "language:chinese",
}

_lock = threading.Lock()
_last = 0.0
_burst = 0


def site_of(cookies: Mapping[str, str]) -> str:
    return "exhentai" if cookies.get("ipb_member_id") and cookies.get("ipb_pass_hash") else "e-hentai"


def _request(net: Net, method: str, url: str, cookies: Mapping[str, str], *, data: bytes | None = None,
             content_type: str = "") -> tuple[int, str, bytes]:
    global _last, _burst
    with _lock:
        wait = _last + INTERVAL_S - time.monotonic()
        _burst += 1
        if _burst > 4:
            wait, _burst = max(wait, 5.0), 0
        if wait > 0:
            time.sleep(wait)
        headers = {"Cookie": "; ".join([f"{k}={v}" for k, v in cookies.items() if v] + ["nw=1"])}
        if content_type:
            headers["Content-Type"] = content_type
        try:
            r = net.request(method, url, data=data, headers=headers, timeout=60)
        finally:
            _last = time.monotonic()
    return r.status, r.headers.get("content-type", ""), r.body


def _check_login(site: str, ctype: str, body: bytes) -> None:
    if site == "exhentai" and (ctype.startswith("image/") or len(body) < 200):
        raise FindError("里站（exhentai）没登录进去：cookie 失效了，重新从浏览器里复制三个 cookie 填进配置")


def galleries(page: str) -> list[tuple[int, str]]:
    seen: dict[int, str] = {}
    for gid, token in GALLERY_RE.findall(page or ""):
        seen.setdefault(int(gid), token)
    return list(seen.items())


def normalize_query(query: str) -> str:
    """中文常用词 → E 站标签；female:bunny girl 这种多词标签自动加引号。"""
    tokens = []
    for tok in str(query or "").split():
        tokens.append(ZH_TAG_ALIASES.get(tok.lower(), ZH_TAG_ALIASES.get(tok, tok)))
    q = " ".join(tokens)
    if not q or '"' in q:
        return q
    ns_re = re.compile(r"^(-?(?:female|male|other|parody|character|group|artist|cosplayer|language|mixed|reclass|temp):)(.+)$", re.I)
    words = q.split(" ")
    out: list[str] = []
    i = 0
    while i < len(words):
        m = ns_re.match(words[i])
        if not m:
            out.append(words[i])
            i += 1
            continue
        group = [m.group(2)]
        j = i + 1
        while j < len(words) and not ns_re.match(words[j]) and not words[j].startswith("-"):
            group.append(words[j])
            j += 1
        out.append(f'{m.group(1)}"{" ".join(group)}"' if len(group) > 1 else words[i])
        i = j
    return " ".join(out)


def _search_page(net: Net, query: str, cookies: Mapping[str, str], site: str, *, page: int = 1) -> tuple[list[tuple[int, str]], bool]:
    """→ (这一页的 (gid, token), 还有没有下一页)。E 站翻页要用上一页的 next 游标，第 N 页就顺着翻过去。"""
    params: dict[str, Any] = {"f_search": query, "f_cats": NOT_DOUJIN}
    cursor = ""
    pairs: list[tuple[int, str]] = []
    for step in range(max(1, min(page, 10))):
        p = dict(params)
        if cursor:
            p["next"] = cursor
        status, ctype, body = _request(net, "GET", SITES[site]["base"] + "/?" + urllib.parse.urlencode(p), cookies)
        if status >= 400:
            raise FindError(f"E 站搜索没成（HTTP {status}）")
        _check_login(site, ctype, body)
        text = body.decode("utf-8", "replace")
        pairs = galleries(text)
        m = re.search(r'id="unext"[^>]*href="([^"]+)"', text)
        cursor = (urllib.parse.parse_qs(urllib.parse.urlparse(html.unescape(m.group(1))).query).get("next") or [""])[0] if m else ""
        if step + 1 < page and not cursor:
            return [], False
    return pairs, bool(cursor)


def _ranking_page(net: Net, mode: str, cookies: Mapping[str, str], site: str, page: int = 1) -> tuple[list[tuple[int, str]], bool]:
    if mode == "popular":
        status, ctype, body = _request(net, "GET", SITES[site]["base"] + "/popular", cookies)
        if status >= 400:
            raise FindError(f"E 站热门榜没打开（HTTP {status}）")
        _check_login(site, ctype, body)
        found = galleries(body.decode("utf-8", "replace"))
        start = (page - 1) * 25
        return found[start:start + 25], start + 25 < len(found)
    tl = TOPLIST.get(mode)
    if not tl:
        raise FindError("排行榜只有：popular（当下热门）/ day（昨日）/ month（上月）/ year（去年）/ all（历史总榜）")
    url = f"https://e-hentai.org/toplist.php?tl={tl}" + (f"&p={page - 1}" if page > 1 else "")
    status, _, body = _request(net, "GET", url, cookies)
    if status >= 400:
        raise FindError(f"E 站排行榜没打开（HTTP {status}）")
    found = galleries(body.decode("utf-8", "replace"))
    return found, len(found) >= 50


def gdata(net: Net, pairs: list[tuple[int, str]], cookies: Mapping[str, str], site: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for i in range(0, len(pairs), 25):
        chunk = [[int(g), str(t)] for g, t in pairs[i:i + 25]]
        body = json.dumps({"method": "gdata", "gidlist": chunk, "namespace": 1}).encode()
        status, _, raw = _request(net, "POST", SITES[site]["api"], cookies, data=body, content_type="application/json")
        if status >= 400:
            raise FindError(f"E 站取本子资料没成（HTTP {status}）")
        try:
            out.extend(m for m in json.loads(raw).get("gmetadata") or [] if not m.get("error"))
        except ValueError as exc:
            raise FindError("E 站资料接口回的不是 JSON") from exc
    return out


def language_of(meta: Mapping[str, Any]) -> str:
    langs = [t.split(":", 1)[1] for t in meta.get("tags") or () if str(t).startswith("language:")
             and t.split(":", 1)[1] not in ("translated", "rewrite")]
    return langs[0] if langs else "japanese"


def screen(metas: list[dict[str, Any]], flt: Filter, withheld: dict[str, int]) -> list[dict[str, Any]]:
    kept = []
    for m in metas:
        if str(m.get("category") or "") in ("Western", "Cosplay", "Asian Porn"):
            continue
        why = flt.hide(tags=m.get("tags") or (), titles=[m.get("title", ""), m.get("title_jpn", "")])
        if why:
            withheld[why] = withheld.get(why, 0) + 1
            continue
        kept.append(m)
    return kept


def brief(meta: Mapping[str, Any], site: str) -> dict[str, Any]:
    gid = int(meta.get("gid") or 0)
    tags = [t for t in meta.get("tags") or () if not str(t).startswith(("language:", "other:"))][:12]
    return {
        "source": "E-Hentai" if site == "e-hentai" else "ExHentai",
        "title": meta.get("title_jpn") or meta.get("title", ""),
        "title_en": meta.get("title", ""),
        "url": f"{SITES[site]['base']}/g/{gid}/{meta.get('token', '')}/",
        "id": gid,
        "pages": int(meta.get("filecount") or 0),
        "language": language_of(meta),
        "rating": meta.get("rating"),
        "category": meta.get("category"),
        "tags": tags,
        "thumb": meta.get("thumb") or "",
    }


def _parse_terms(query: str) -> list[tuple[str | None, str, bool]]:
    q = normalize_query(query)
    pattern = re.compile(r'(-?)(?:(female|male|other|parody|character|group|artist|cosplayer|language|mixed):)?(?:"([^"]+)"|(\S+))', re.I)
    terms = []
    for m in pattern.finditer(q):
        val = (m.group(3) or m.group(4) or "").strip().rstrip("$").lower()
        if val:
            terms.append((m.group(2).lower() if m.group(2) else None, val, m.group(1) == "-"))
    return terms


def _matches(meta: Mapping[str, Any], terms: list[tuple[str | None, str, bool]]) -> bool:
    tags = [str(t).lower() for t in meta.get("tags") or ()]
    names = [t.split(":", 1)[1] if ":" in t else t for t in tags]
    blob = f"{meta.get('title') or ''} {meta.get('title_jpn') or ''}".lower()
    for ns, val, neg in terms:
        hit = (f"{ns}:{val}" in tags or val in names) if ns else (any(val in t for t in tags) or val in blob)
        if hit == neg:
            return False
    return True


def search(net: Net, cookies: Mapping[str, str], flt: Filter, *, query: str = "", ranking: str = "", page: int = 1,
           limit: int = 8, language: str = "chinese") -> dict[str, Any]:
    """→ {items: [gdata 元数据], site, has_more, label, withheld: {minor, block}}"""
    site = site_of(cookies)
    withheld: dict[str, int] = {}
    q = normalize_query(query)
    ranking = ranking.strip().lower()
    if ranking and ranking not in RANKING_LABELS:
        raise FindError("排行榜只有：popular（当下热门）/ day（昨日）/ month（上月）/ year（去年）/ all（历史总榜）")
    if ranking:
        terms = _parse_terms(query) if query else []
        kept: list[dict[str, Any]] = []
        has_more = False
        for p in range(page, page + (1 if ranking == "popular" or not terms else 4)):
            found, has_more = _ranking_page(net, ranking, cookies, site, p)
            if not found:
                break
            kept += [m for m in screen(gdata(net, found[:50], cookies, site), flt, withheld) if not terms or _matches(m, terms)]
            if len(kept) >= limit or not has_more:
                break
        label = RANKING_LABELS[ranking] + (f" · 筛「{query}」" if query else "") + (f"（第 {page} 页）" if page > 1 else "")
    else:
        found, has_more = _search_page(net, f"{q} {flt.eh_exclusions()}".strip(), cookies, site, page=page)
        kept = screen(gdata(net, found[:25], cookies, site), flt, withheld)
        label = query + (f"（第 {page} 页）" if page > 1 else "")
    if language:
        kept.sort(key=lambda m: (language_of(m) != language, -float(m.get("rating") or 0)) if not ranking
                  else (language_of(m) != language))
    return {"items": kept, "site": site, "has_more": has_more, "label": label, "withheld": withheld}


# ── 以图搜本 ─────────────────────────────────────────────────────────────────────
def core_title(name: str) -> str:
    """「(C97) [社团 (作者)] 本名 (原作) [中国翻訳]」→「本名」。"""
    text = name or ""
    for _ in range(5):
        stripped = BRACKETS_RE.sub(" ", text)
        if stripped == text:
            break
        text = stripped
    return " ".join(text.split())


def similar(a: str, b: str) -> float:
    a, b = core_title(a).lower(), core_title(b).lower()
    return difflib.SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def file_search(net: Net, image: bytes, cookies: Mapping[str, str]) -> list[tuple[int, str]]:
    """E 站「以图搜本」：只认得原图 / 高度相似的整页（截过、压过的多半对不上）。"""
    site = site_of(cookies)
    body, ctype = multipart([("f_sfile", "search"), ("fs_similar", "on")], "sfile", "page.jpg", image)
    status, ct, raw = _request(net, "POST", SITES[site]["upload"], cookies, data=body, content_type=ctype)
    if status >= 400:
        raise FindError(f"E 站以图搜本没成（HTTP {status}）")
    _check_login(site, ct, raw)
    return galleries(raw.decode("utf-8", "replace"))


def gtoken(net: Net, cookies: Mapping[str, str], gid: int, page_token: str, page_no: int) -> tuple[int, str] | None:
    """单页链接 /s/<页 token>/<gid>-<页码> → (gid, 本子 token)。"""
    site = site_of(cookies)
    body = json.dumps({"method": "gtoken", "pagelist": [[int(gid), page_token, int(page_no)]]}).encode()
    status, _, raw = _request(net, "POST", SITES[site]["api"], cookies, data=body, content_type="application/json")
    if status >= 400:
        return None
    try:
        row = (json.loads(raw).get("tokenlist") or [{}])[0]
    except (ValueError, IndexError):
        return None
    return (int(row["gid"]), str(row["token"])) if row.get("gid") and row.get("token") else None


def by_gid_token(net: Net, cookies: Mapping[str, str], pairs: list[tuple[int, str]]) -> list[dict[str, Any]]:
    return gdata(net, pairs, cookies, site_of(cookies)) if pairs else []
