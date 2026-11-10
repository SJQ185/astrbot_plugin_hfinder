"""hanime1.me（中文字幕里番站）：按标签 / 片名 / 分区 / 排行搜，回播放页链接。

每部都打开播放页核一遍标签（红线 + 使用者的「不想看」），核不了的不列。播放页资料存 3 天，标签表存 7 天。
连接：先直连；被 Cloudflare 拦了、又配了浏览器，就借浏览器在 hanime1 页面里同源取（和人用浏览器看一样）。
浏览器也停在人机验证上 → 让人去点；没配浏览器 → 报 H1Down（上层改用 AniList 查资料）。
"""

from __future__ import annotations

import concurrent.futures
import difflib
import html as _html
import json
import re
import threading
import time
import unicodedata
import urllib.parse
from pathlib import Path
from typing import Any, Iterable, Mapping

from .net import Net, NetError, looks_challenged
from .redline import Filter
from .settings import FindError, NeedVerify

BASE = "https://hanime1.me"
HEADERS = {"Accept-Language": "zh-CN,zh;q=0.9"}           # zh-CN → 标签显示名是简体

GENRES = ("裏番", "泡麵番", "Motion Anime", "3DCG", "2.5D", "2D動畫", "AI生成", "MMD")
ALL_GENRES = "全部"
GENRE_ALIASES = {"里番": "裏番", "裏番": "裏番", "泡面番": "泡麵番", "泡麵番": "泡麵番", "motionanime": "Motion Anime",
                 "动态漫画": "Motion Anime", "動態漫畫": "Motion Anime", "3d": "3DCG", "3dcg": "3DCG", "3d动画": "3DCG",
                 "2.5d": "2.5D", "2d动画": "2D動畫", "2d動畫": "2D動畫", "ai": "AI生成", "ai生成": "AI生成", "mmd": "MMD",
                 "全部": ALL_GENRES, "all": ALL_GENRES}
GENRE_LABEL = {"裏番": "里番", "泡麵番": "泡面番", "Motion Anime": "动态漫画", "3DCG": "3D", "2.5D": "2.5D",
               "2D動畫": "2D动画", "AI生成": "AI生成", "MMD": "MMD", ALL_GENRES: "全部"}
SORTS = {"popular": "觀看次數", "score": "讚好比例", "newest": "最新上市", "trending": "本週排行",
         "uploaded": "最新上傳", "month": "本月排行", "today": "本日排行", "longest": "時長最長"}
SORT_LABEL = {"popular": "播放最多", "score": "好评最多", "newest": "最新上市", "trending": "本周排行",
              "uploaded": "最新上传", "month": "本月排行", "today": "本日排行", "longest": "最长"}
ALIASES = {
    "阿黑颜": "阿嘿顏", "后庭": "肛交", "走后门": "肛交", "足交": "腳交", "扶她": "扶他", "舔肛": "毒龍鑽", "毒龙": "毒龍鑽",
    "道具": "性玩具", "玩具": "性玩具", "透视": "斷面圖", "剖面": "斷面圖", "断面": "斷面圖", "x光": "斷面圖", "女王": "女王樣",
    "中出": "內射", "无码": "無碼", "中文": "中文字幕", "牛头人": "NTR", "强奸": "強制", "催眠": "精神控制", "洗脑": "精神控制",
    "母乳": "噴奶", "喷乳": "噴奶", "尿": "放尿", "露出": "公眾場合", "户外": "戶外野戰", "野战": "戶外野戰", "黑皮": "黑皮膚",
    "男娘": "偽娘", "女装": "偽娘", "触手": "觸手", "怀孕": "懷孕", "多p": "群交", "捆绑": "綑綁", "束缚": "綑綁",
    "深喉": "深喉嚨", "舔阴": "舔穴", "后入": "背後位", "骑乘": "騎乘位", "女上": "騎乘位", "丝袜": "絲襪", "黑丝": "絲襪",
    "白丝": "絲襪", "女仆装": "女僕", "精灵": "妖精", "猎奇": "獵奇", "腹凸": "胃凸",
}
PACE_GAP = 0.5
WATCH_DAYS = 3
VOCAB_DAYS = 7
NEED_BROWSER = ("hanime1 被 Cloudflare 拦了（服务器 IP 常被拦）。要搜 hanime1，在配置里填一个开着远程调试的浏览器（browser_cdp），"
                "这次先用 AniList 查的资料")


class H1Error(FindError):
    pass


class H1Down(H1Error):
    """站连不上 / 被拦（上层改用 AniList）。"""


_PACE = {"lock": threading.Lock(), "next": 0.0}
_STATE = {"browser_until": 0.0}


def _pace(gap: float = PACE_GAP) -> None:
    with _PACE["lock"]:
        now = time.time()
        at = max(now, _PACE["next"])
        _PACE["next"] = at + gap
    if at > now:
        time.sleep(at - now)


_FETCH_JS = """(async (paths) => {
  const out = {};
  for (let i = 0; i < paths.length; i += 3) {
    if (i) await new Promise(r => setTimeout(r, 1000));
    await Promise.all(paths.slice(i, i + 3).map(async p => {
      try { const r = await fetch(p, {credentials: 'include'}); out[p] = [r.status, await r.text()]; }
      catch (e) { out[p] = [0, String(e)]; }
    }));
  }
  return out;
})(%s)"""


class Hanime1:
    def __init__(self, net: Net, flt: Filter, cache: Path) -> None:
        self.net, self.flt, self.cache = net, flt, Path(cache)

    # ── 取页面 ───────────────────────────────────────────────────────────────
    def _direct(self, path: str) -> str:
        _pace()
        try:
            r = self.net.get(BASE + path, headers=HEADERS, timeout=25, limit=6 * 1024 * 1024)
        except NetError as exc:
            raise H1Down(f"hanime1 没连上（{exc}）") from exc
        text = r.text()
        if looks_challenged(r.status, text):
            raise _Blocked()
        if r.status != 200:
            raise H1Down(f"hanime1 回了 HTTP {r.status}")
        return text

    def get_many(self, paths: Iterable[str]) -> dict[str, str]:
        paths = list(dict.fromkeys(paths))
        out: dict[str, str] = {}
        blocked = time.time() < _STATE["browser_until"]
        if not blocked:
            errors: list[Exception] = []

            def one(p: str) -> tuple[str, str, Exception | None]:
                try:
                    return p, self._direct(p), None
                except (H1Error, _Blocked) as exc:
                    return p, "", exc

            with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
                for p, text, err in pool.map(one, paths):
                    if err is None:
                        out[p] = text
                    else:
                        errors.append(err)
            if not any(isinstance(e, _Blocked) for e in errors):
                if errors and not out:
                    raise errors[0]
                return out
            _STATE["browser_until"] = time.time() + 1800              # 被拦了：半小时内直接走浏览器
        if not self.net.has_browser:
            if out:
                return out
            raise H1Down(NEED_BROWSER)
        rest = [p for p in paths if p not in out]
        got = self.net.in_page(BASE + "/", _FETCH_JS % json.dumps(rest, ensure_ascii=False), site="hanime1",
                               timeout=max(90.0, len(rest) * 0.6 + 60)) or {}
        for p, v in got.items():
            if not (isinstance(v, list) and len(v) == 2):
                continue
            status, text = int(v[0]), str(v[1])
            if looks_challenged(status, text):
                raise NeedVerify("hanime1 弹了 Cloudflare 人机验证：请在你配置的那个浏览器里打开 https://hanime1.me 点一下验证，再搜一次")
            if status == 200:
                out[p] = text
        if not out:
            raise H1Down("hanime1 一页都没取到")
        return out

    # ── 播放页 ───────────────────────────────────────────────────────────────
    def watch_items(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        folder = self.cache / "hanime1_watch"
        out, need = {}, []
        for vid in ids:
            try:
                data = json.loads((folder / f"{vid}.json").read_text(encoding="utf-8"))
                if time.time() - float(data.get("_at") or 0) < WATCH_DAYS * 86400:
                    data["_values"] = set(data.get("_values") or [])
                    out[vid] = data
                    continue
            except (OSError, ValueError, TypeError):
                pass
            need.append(vid)
        if need:
            try:
                pages = self.get_many([f"/watch?v={vid}" for vid in need])
            except NeedVerify:
                raise
            except H1Down:
                pages = {}
            folder.mkdir(parents=True, exist_ok=True)
            for vid in need:
                raw = pages.get(f"/watch?v={vid}")
                if not raw:
                    continue
                item = parse_watch(vid, raw)
                out[vid] = item
                if item["_checked"]:
                    try:
                        (folder / f"{vid}.json").write_text(json.dumps(
                            {**item, "_values": sorted(item["_values"]), "_at": time.time()}, ensure_ascii=False),
                            encoding="utf-8")
                    except OSError:
                        pass
        return out

    def _hide(self, item: Mapping[str, Any]) -> str:
        return self.flt.hide(tags=item.get("_values") or (), titles=[item.get("title"), item.get("title_zh")],
                             texts=[item.get("description")])

    # ── 标签表 ───────────────────────────────────────────────────────────────
    def vocab(self) -> list[tuple[str, str]]:
        path = self.cache / "hanime1_tags.json"
        cached: list[tuple[str, str]] = []
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            cached = [(str(v), str(l)) for v, l in data.get("tags") or []]
            if cached and time.time() - float(data.get("at") or 0) < VOCAB_DAYS * 86400:
                return cached
        except (OSError, ValueError, TypeError):
            pass
        try:
            page = next(iter(self.get_many([f"/search?genre={urllib.parse.quote('裏番')}"]).values()))
        except H1Error:
            if cached:
                return cached
            raise
        pairs = [(_html.unescape(v).strip(), _html.unescape(l).strip()) for v, l in re.findall(
            r'name="tags\[\]"[^>]*\bvalue="([^"]+)"[^>]*>\s*<span[^>]*>\s*([^<]+?)\s*</span>', page)]
        if not pairs:
            if cached:
                return cached
            raise H1Down("hanime1 搜索页里没找到标签表（页面改版了？）")
        path.write_text(json.dumps({"at": time.time(), "tags": pairs}, ensure_ascii=False), encoding="utf-8")
        return pairs

    # ── 搜 ──────────────────────────────────────────────────────────────────
    def search(self, *, tags: list[str], exclude: list[str], query: str, genre: str, sort: str, page: int,
               limit: int) -> dict[str, Any]:
        """→ {items: [(公开资料, 封面链接)], has_more, label, withheld}"""
        pairs = self.vocab()
        labels = {v: l for v, l in pairs}
        inc, unknown = resolve_terms(tags, pairs)
        exc, unknown_ex = resolve_terms(exclude, pairs)
        if unknown or unknown_ex:
            raise H1Error("hanime1 上没有这些标签：" + "；".join(
                f"「{t}」" + (f"（相近的：{'、'.join(n)}）" if n else "") for t, n in unknown + unknown_ex)
                + "。换成相近的，或者当片名搜")
        g = _genre(genre)
        sort_value = SORTS.get(sort, "") if sort else ("" if query else SORTS["popular"])
        path = search_path(tags=inc, query=query, genre=g, sort=sort_value, page=page)
        page_html = self.get_many([path])[path]
        cards = parse_cards(page_html)
        has_more = re.search(rf"[?&;]page={page + 1}\b", page_html) is not None
        items, withheld = self._screen(cards, limit, set(exc), labels)
        bits = [GENRE_LABEL.get(g, g)] + [labels.get(t, t) for t in inc] + ([f"「{query}」"] if query else [])
        bits.append(SORT_LABEL.get(sort, "") if sort else ("" if query else "播放最多"))
        return {"items": items, "has_more": has_more, "withheld": withheld,
                "label": " · ".join(b for b in bits if b) + (f"（第 {page} 页）" if page > 1 else "")}

    def _screen(self, cards: list[dict[str, Any]], limit: int, exc: set[str], labels: Mapping[str, str]
                ) -> tuple[list[tuple[dict[str, Any], str]], dict[str, int]]:
        withheld: dict[str, int] = {}
        items: list[tuple[dict[str, Any], str]] = []
        i = 0
        while i < len(cards) and len(items) < limit:
            batch = cards[i:i + max(8, (limit - len(items)) * 3)]
            i += len(batch)
            got = self.watch_items([c["id"] for c in batch])
            for c in batch:
                item = got.get(c["id"])
                if item is None or not item["_checked"]:
                    withheld["unchecked"] = withheld.get("unchecked", 0) + 1
                    continue
                item["title_zh"] = item["title_zh"] or c["title_zh"]
                why = self._hide(item)
                if why:
                    withheld[why] = withheld.get(why, 0) + 1
                elif exc & item["_values"]:
                    withheld["excluded"] = withheld.get("excluded", 0) + 1
                elif len(items) < limit:
                    items.append((public(item, labels), c.get("cover") or ""))
        return items, withheld

    def lookup(self, titles: list[str], episode: str = "") -> dict[str, Any]:
        """截图认出片名以后：[原名, 罗马字…] + 第几集 → {links} / {withheld: True} / {}（没找到）。"""
        for title in [t for t in titles if t][:2]:
            key = _norm(title)
            if len(key) < 2:
                continue
            for g in ("裏番", "泡麵番"):
                path = search_path(tags=[], query=title, genre=g, sort="", page=1)
                cards = parse_cards(self.get_many([path])[path])[:8]
                if not cards:
                    continue
                got = self.watch_items([c["id"] for c in cards])
                found = []
                for c in cards:
                    item = got.get(c["id"])
                    if item is None:
                        continue
                    item["title_zh"] = item["title_zh"] or c["title_zh"]
                    nt = _norm(item["title"])
                    if key in nt or (len(nt) >= 4 and nt in key):
                        found.append(item)
                if not found:
                    continue
                if any(not it["_checked"] or self._hide(it) for it in found):
                    return {"withheld": True}
                same = [it for it in found if episode and _ep_of(it) == str(episode).split("、")[0].strip()]
                pick = (same or found)[:3]
                return {"links": [{"title": it.get("title_zh") or it.get("title"), "url": it["url"],
                                   "subtitles": public(it, {}).get("subtitles", ""), "episode": _ep_of(it)} for it in pick],
                        "episode_matched": bool(same)}
        return {}


class _Blocked(Exception):
    """直连被 Cloudflare 拦了（内部用）。"""


# ── 解析 ─────────────────────────────────────────────────────────────────────────
def _text(fragment: str) -> str:
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>", " ", fragment))).strip()


def parse_cards(page: str) -> list[dict[str, Any]]:
    """搜索页 → [{id, title_zh, cover, duration?, views?}]（竖封面和横缩略图两种卡片都认）。"""
    cards, seen = [], set()
    for m in re.finditer(r'<a\b[^>]*href="(?:https://hanime1\.me)?/watch\?v=(\d+)"[^>]*>(.*?)</a>', page, re.S):
        vid, block = m.group(1), m.group(2)
        title = re.search(r'class="(home-rows-videos-title|title)"[^>]*>(.*?)</div>', block, re.S)
        if vid in seen or not title:
            continue
        seen.add(vid)
        img = re.search(r'<img\b[^>]*\bsrc="([^"]+)"', block)
        card: dict[str, Any] = {"id": vid, "title_zh": _text(title.group(2)), "cover": _html.unescape(img.group(1)) if img else ""}
        dur = re.search(r'class="duration"[^>]*>\s*([\d:]+)\s*<', block)
        if dur:
            card["duration"] = dur.group(1)
        cards.append(card)
    return cards


def _metas(page: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for tag in re.findall(r"<meta\b[^>]*>", page[:200_000]):
        attrs = dict(re.findall(r'([\w:-]+)="([^"]*)"', tag))
        key = attrs.get("property") or attrs.get("name")
        if key and "content" in attrs:
            out.setdefault(key, _html.unescape(attrs["content"]))
    return out


def _clock(seconds: Any) -> str:
    try:
        s = int(float(seconds))
    except (TypeError, ValueError):
        return ""
    h, rest = divmod(s, 3600)
    return f"{h}:{rest // 60:02d}:{rest % 60:02d}" if h else f"{rest // 60}:{rest % 60:02d}"


def parse_watch(vid: str, page: str) -> dict[str, Any]:
    """播放页 → 资料；_values 是核标签用的全集（标签区 + keywords）。"""
    meta = _metas(page)
    share = re.search(r'id="shareBtn-title"[^>]*>(.*?)<', page, re.S)
    original = _text(share.group(1)) if share else re.sub(r"\s*-\s*Hanime1\.me\s*$", "", meta.get("og:title", "")).strip()
    og_desc = meta.get("og:description", "")
    title_zh, desc = (og_desc.split(" - ", 1) + [""])[:2] if " - " in og_desc else ("", og_desc)
    tags = []
    for href, label, votes in re.findall(
            r'href="/search\?tags%5B%5D=([^"&]+)[^"]*"[^>]*>\s*([^<]*?)\s*(?:&nbsp;)?\s*<span[^>]*>\s*\((\d+)\)\s*</span>', page):
        value = urllib.parse.unquote(_html.unescape(href)).strip()
        tags.append({"value": value, "label": _html.unescape(label).replace("\xa0", " ").strip() or value, "votes": int(votes)})
    keywords = [k.strip() for k in meta.get("keywords", "").split(",") if k.strip()]
    panel = page[page.find("video-description-panel"):][:6000] if "video-description-panel" in page else ""
    panel_text = _text(panel)
    views = re.search(r"(?:觀看次數|观看次数)\s*[:：]\s*([\d.,]+\s*[萬万億亿]?次?)", panel_text)
    date = re.search(r"\b(20\d\d-\d\d-\d\d)\b", panel_text)
    artist = re.search(r'id="video-artist-name"[^>]*>\s*([^<]+?)\s*<', page)
    values = {t["value"] for t in tags} | set(keywords)
    return {
        "id": vid, "url": f"{BASE}/watch?v={vid}", "title": original, "title_zh": title_zh.strip(),
        "description": desc.strip(), "tags": sorted(tags, key=lambda t: -t["votes"]),
        "studio": artist.group(1) if artist else "", "views": views.group(1).replace(" ", "") if views else "",
        "date": date.group(1) if date else "", "duration": _clock(meta.get("og:video:duration")),
        "chinese_subs": "中文字幕" in original or "中文字幕" in values, "chinese_dub": "中文配音" in values,
        "uncensored": "無碼" in values or "無碼" in original,
        "_values": values, "_checked": bool(tags or keywords),
    }


def public(item: Mapping[str, Any], labels: Mapping[str, str], max_tags: int = 8) -> dict[str, Any]:
    tag_names = [labels.get(t["value"], t["label"]) for t in item.get("tags") or []][:max_tags]
    subs = "中文字幕" if item.get("chinese_subs") else ("中文配音" if item.get("chinese_dub") else "")
    out = {"title": item.get("title") or "", "title_zh": item.get("title_zh") or "", "url": item.get("url") or "",
           "subtitles": subs, "uncensored": bool(item.get("uncensored")), "studio": item.get("studio") or "",
           "date": item.get("date") or "", "views": item.get("views") or "", "duration": item.get("duration") or "",
           "tags": tag_names}
    return {k: v for k, v in out.items() if v not in ("", None, [], False)}


def resolve_terms(terms: list[str], pairs: list[tuple[str, str]]) -> tuple[list[str], list[tuple[str, list[str]]]]:
    """用户的词（简体 / 繁体 / 常见叫法）→ (站上的标签值, [(不认识的词, 相近的标签)])。"""
    values = {v for v, _ in pairs}
    by_lower = {v.lower(): v for v in values}
    by_label: dict[str, str] = {}
    s2t: dict[str, str] = {}
    for v, l in pairs:
        by_label.setdefault(l.lower(), v)
        if len(v) == len(l):
            for a, b in zip(l, v):
                if a != b:
                    s2t.setdefault(a, b)
    got, unknown = [], []
    for term in terms:
        low = term.lower()
        cand = ALIASES.get(term) or ALIASES.get(low) or by_lower.get(low) or by_label.get(low)
        if not cand:
            cand = by_lower.get("".join(s2t.get(c, c) for c in term).lower())
        if cand and cand in values:
            got.append(cand)
            continue
        labels = [l for _, l in pairs]
        near = [l for l in labels if term in l or l in term][:6] or difflib.get_close_matches(term, labels, n=6, cutoff=0.4)
        unknown.append((term, near))
    return list(dict.fromkeys(got)), unknown


def _genre(raw: Any) -> str:
    g = str(raw or "").strip()
    if not g:
        return "裏番"
    got = GENRE_ALIASES.get(g) or GENRE_ALIASES.get(g.lower().replace(" ", ""))
    if got:
        return got
    if g in GENRES:
        return g
    raise H1Error("hanime1 的分区只有：" + "、".join(GENRE_LABEL[x] for x in GENRES) + "（或者「全部」）")


def search_path(*, tags: list[str], query: str, genre: str, sort: str, page: int) -> str:
    params: list[tuple[str, str]] = [("query", query), ("genre", genre)]
    if sort:
        params.append(("sort", sort))
    params += [("tags[]", t) for t in tags]
    if page > 1:
        params.append(("page", str(page)))
    return "/search?" + urllib.parse.urlencode(params)


def search_url(query: str) -> str:
    """给人自己点开的 hanime1 搜索链接（站被拦、只好退 AniList 时附上）。"""
    return BASE + search_path(tags=[], query=query, genre=ALL_GENRES, sort="", page=1)


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "").lower()
    s = re.sub(r"\b(ova|the animation)\b", "", s)
    return re.sub(r"[\W_]+", "", s)


def _ep_of(item: Mapping[str, Any]) -> str:
    for text in (item.get("title") or "", item.get("title_zh") or ""):
        m = re.search(r"(?:[＃#]|第)\s*(\d+)|(\d+)\s*(?:話|话|集)?\s*(?:\[[^\]]*\])?\s*$", text)
        if m:
            return str(int(m.group(1) or m.group(2)))
    return ""
