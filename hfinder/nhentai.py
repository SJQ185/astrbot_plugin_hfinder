"""nhentai（N 站）：新接口 /api/v2 搜索、按编号取资料。不用登录。"""

from __future__ import annotations

import re
import threading
import urllib.parse
from typing import Any, Mapping

from .net import Net
from .redline import Filter
from .settings import FindError

API = "https://nhentai.net/api/v2"
THUMB_HOSTS = ("https://t3.nhentai.net", "https://t2.nhentai.net", "https://t1.nhentai.net", "https://t4.nhentai.net")
SORTS = {"popular": "热门总榜", "popular-today": "今日热门", "popular-week": "本周热门", "popular-month": "本月热门", "date": "最新"}

ZH_ALIASES: dict[str, str] = {
    "肛交": 'tag:"anal"', "走后门": 'tag:"anal"', "后庭": 'tag:"anal"', "尿道": 'tag:"urethra insertion"',
    "丝袜": 'tag:"stockings"', "连裤袜": 'tag:"pantyhose"', "裤袜": 'tag:"pantyhose"', "白丝": 'tag:"stockings"',
    "黑丝": 'tag:"stockings"', "足交": 'tag:"footjob"', "口交": 'tag:"blowjob"', "乳交": 'tag:"paizuri"',
    "触手": 'tag:"tentacles"', "催眠": 'tag:"mind control"', "常识改变": 'tag:"mind control"', "人妻": 'tag:"milf"',
    "熟女": 'tag:"milf"', "牛头人": 'tag:"netorare"', "纯爱": 'tag:"vanilla"', "百合": 'tag:"yuri"',
    "捆绑": 'tag:"bondage"', "调教": 'tag:"bdsm"', "内射": 'tag:"nakadashi"', "中出": 'tag:"nakadashi"',
    "颜射": 'tag:"bukkake"', "阿黑颜": 'tag:"ahegao"', "泳装": 'tag:"swimsuit"', "女仆": 'tag:"maid"',
    "修女": 'tag:"nun"', "巫女": 'tag:"miko"', "兔女郎": 'tag:"bunny girl"', "精灵": 'tag:"elf"', "魅魔": 'tag:"succubus"',
    "灌肠": 'tag:"enema"', "拉珠": 'tag:"anal beads"', "全彩": 'tag:"full color"', "无修正": 'tag:"uncensored"',
    "无码": 'tag:"uncensored"', "中文": "language:chinese", "汉化": "language:chinese",
}

_tag_lock = threading.Lock()
_tag_cache: dict[int, dict[str, Any]] = {}


def _api(net: Net, path: str, params: Mapping[str, Any] | None = None, timeout: int = 25) -> Any:
    url = API + path
    if params:
        qs = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        url += "?" + qs if qs else ""
    r = net.get(url, headers={"Accept": "application/json"}, timeout=timeout, limit=10 * 1024 * 1024)
    if r.status == 404:
        return None
    if r.status != 200:
        raise FindError(f"N 站接口回了 HTTP {r.status}")
    return r.json()


def _resolve_tags(net: Net, tag_ids: list[int]) -> dict[int, dict[str, Any]]:
    missing = sorted({int(t) for t in tag_ids} - set(_tag_cache))
    for i in range(0, len(missing), 80):
        try:
            rows = _api(net, "/tags/ids", {"ids": ",".join(str(x) for x in missing[i:i + 80])}, timeout=20)
        except FindError:
            continue
        with _tag_lock:
            for r in rows or []:
                if isinstance(r, dict) and "id" in r:
                    _tag_cache[int(r["id"])] = r
    return {int(t): _tag_cache[int(t)] for t in tag_ids if int(t) in _tag_cache}


def normalize_query(raw: str, language: str = "chinese") -> str:
    s = " ".join(str(raw or "").split())
    for zh, en in sorted(ZH_ALIASES.items(), key=lambda kv: -len(kv[0])):
        if zh in s:
            s = s.replace(zh, f" {en} ")
    s = re.sub(r'\b(?:female|male|other):"([^"]+)"', r'tag:"\1"', s, flags=re.I)
    s = re.sub(r"\b(?:female|male|other):([a-zA-Z0-9_-]+)", r"tag:\1", s, flags=re.I)
    s = " ".join(s.split())
    if language and language != "all" and "language:" not in s.lower():
        s = f"{s} language:{language}".strip()
    return s


def to_meta(item: Mapping[str, Any], tag_map: Mapping[int, Mapping[str, Any]]) -> dict[str, Any]:
    if isinstance(item.get("title"), dict):
        title_en = str(item["title"].get("english") or item["title"].get("pretty") or "")
        title_jp = str(item["title"].get("japanese") or title_en)
    else:
        title_en = str(item.get("english_title") or "")
        title_jp = str(item.get("japanese_title") or title_en)
    tags: list[str] = []
    category = "Doujinshi"
    raw_tags = item.get("tags") if isinstance(item.get("tags"), list) else [tag_map.get(int(t)) for t in item.get("tag_ids") or ()]
    for t in raw_tags:
        if not isinstance(t, dict):
            continue
        kind, name = str(t.get("type") or "tag"), str(t.get("name") or "").lower()
        if kind == "category":
            category = name.capitalize()
        else:
            tags.append(f"{kind}:{name}")
    thumb = item.get("thumbnail")
    rel = str(thumb.get("path") or "") if isinstance(thumb, dict) else str(thumb or "")
    return {"gid": int(item.get("id") or 0), "title": title_en, "title_jpn": title_jp,
            "filecount": int(item.get("num_pages") or 0), "favorites": int(item.get("num_favorites") or 0),
            "category": category, "tags": tags, "thumb": f"{THUMB_HOSTS[0]}/{rel.lstrip('/')}" if rel else "",
            "_tags_known": bool(tags)}


def language_of(meta: Mapping[str, Any]) -> str:
    langs = [t.split(":", 1)[1] for t in meta.get("tags") or () if str(t).startswith("language:")
             and t.split(":", 1)[1] not in ("translated", "rewrite")]
    return langs[0] if langs else "japanese"


def hide(meta: Mapping[str, Any], flt: Filter) -> str:
    if str(meta.get("category") or "").lower() == "western":
        return "skip"
    if not meta.get("_tags_known"):
        return "minor"                                   # 标签没取到，核不了：先不列
    return flt.hide(tags=meta.get("tags") or (), titles=[meta.get("title", ""), meta.get("title_jpn", "")])


def brief(meta: Mapping[str, Any]) -> dict[str, Any]:
    gid = int(meta["gid"])
    return {
        "source": "nhentai", "id": gid,
        "title": meta.get("title_jpn") or meta.get("title", ""), "title_en": meta.get("title", ""),
        "url": f"https://nhentai.net/g/{gid}/", "pages": int(meta.get("filecount") or 0),
        "language": language_of(meta), "favorites": int(meta.get("favorites") or 0), "category": meta.get("category"),
        "tags": [t.split(":", 1)[1] for t in meta.get("tags") or () if t.startswith("tag:")][:12],
        "thumb": meta.get("thumb") or "",
    }


def search(net: Net, flt: Filter, *, query: str = "", sort: str = "popular", page: int = 1, limit: int = 8,
           language: str = "chinese") -> dict[str, Any]:
    sort = sort if sort in SORTS else "popular"
    full = f"{normalize_query(query, language)} {flt.nh_exclusions()}".strip()
    withheld: dict[str, int] = {}
    kept: list[dict[str, Any]] = []
    cur, total = page, page
    for _ in range(3):
        data = _api(net, "/search", {"query": full, "sort": sort, "page": cur}) or {}
        items = data.get("result") or [] if isinstance(data, dict) else []
        total = int(data.get("num_pages") or cur) if isinstance(data, dict) else cur
        if not items:
            break
        tag_map = _resolve_tags(net, [int(x) for it in items for x in it.get("tag_ids") or ()])
        for it in items:
            m = to_meta(it, tag_map)
            why = hide(m, flt)
            if why:
                if why != "skip":
                    withheld[why] = withheld.get(why, 0) + 1
                continue
            kept.append(m)
        if len(kept) >= limit or cur >= total:
            break
        cur += 1
    return {"items": kept[:limit], "has_more": cur < total, "withheld": withheld,
            "label": f"{query or '全部'} · {SORTS[sort]}" + (f"（第 {page} 页）" if page > 1 else "")}


def gallery(net: Net, gid: int) -> dict[str, Any] | None:
    item = _api(net, f"/galleries/{int(gid)}")
    return to_meta(item, {}) if isinstance(item, dict) and item.get("id") else None
