"""动画截图找出处（trace.moe + SauceNAO 动画库）和 AniList 资料 / 按标签搜。

trace.moe：免登录每 24 小时 100 次（按出口 IP 算），同一时间只能一个请求；收录成人动画。
视频 / GIF 用 ffmpeg 抽几帧分别查、按「哪部 + 第几集」投票（没装 ffmpeg 就只认图片）。
AniList：免登录，限速每分钟 30 次。回的是资料，不是播放地址。
"""

from __future__ import annotations

import difflib
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any, Mapping

from .net import Net, NetError, multipart
from .redline import Filter
from .settings import FindError

TRACE = "https://api.trace.moe"
ANILIST = "https://graphql.anilist.co"
SAUCE = "https://saucenao.com/search.php"
SURE, MAYBE = 0.90, 0.87
SAUCE_MIN = 80.0
VIDEO_EXT = {".mp4", ".m4v", ".mkv", ".webm", ".mov", ".avi", ".flv", ".wmv", ".ts", ".3gp", ".gif"}
MEDIA_FIELDS = ("id title{native romaji english} synonyms format episodes seasonYear averageScore isAdult genres "
                "tags{name rank} studios(isMain:true){nodes{name}} siteUrl coverImage{large}")
FORMAT_ZH = {"TV": "TV", "TV_SHORT": "短篇", "MOVIE": "剧场版", "SPECIAL": "特别篇", "OVA": "OVA", "ONA": "网络动画"}
SORTS = {"popular": "POPULARITY_DESC", "score": "SCORE_DESC", "newest": "START_DATE_DESC", "trending": "TRENDING_DESC"}

# 中文 → AniList 标签 / 类型（第一个中文叫法用来显示）
ZH_TAGS: dict[str, str] = {
    "里番": "Hentai", "卖肉": "Ecchi", "恋爱": "Romance", "搞笑": "Comedy", "奇幻": "Fantasy", "剧情": "Drama",
    "阿黑颜": "Ahegao", "肛交": "Anal Sex", "后庭": "Anal Sex", "足交": "Ashikoki", "捆绑": "Bondage", "乳交": "Boobjob",
    "深喉": "Deepthroat", "双插": "Double Penetration", "露出": "Exhibitionism", "颜射": "Facial", "口交": "Fellatio",
    "女王": "Femdom", "扶她": "Futanari", "群交": "Group Sex", "手交": "Handjob", "母乳": "Lactation",
    "巨乳": "Large Breasts", "自慰": "Masturbation", "熟女": "MILF", "人妻": "MILF", "内射": "Nakadashi", "中出": "Nakadashi",
    "牛头人": "Netorare", "NTR": "Netorare", "公开": "Public Sex", "强奸": "Rape", "舔肛": "Rimjob", "道具": "Sex Toys",
    "潮吹": "Squirting", "触手": "Tentacles", "3P": "Threesome", "处女": "Virginity", "放尿": "Watersports",
    "女仆": "Maids", "修女": "Nun", "巫女": "Shrine Maiden", "精灵": "Elf", "兽耳": "Kemonomimi", "猫耳": "Nekomimi",
    "魅魔": "Succubus", "魔物娘": "Monster Girl", "吸血鬼": "Vampire", "魔女": "Witch", "OL": "Office Lady",
    "辣妹": "Gyaru", "黑皮": "Tanned Skin", "后宫": "Female Harem", "百合": "Yuri", "乱伦": "Incest", "异种": "Interspecies",
    "出轨": "Cheating", "怀孕": "Pregnancy", "催眠": "Brainwashing", "洗脑": "Brainwashing", "威胁": "Blackmail",
    "异世界": "Isekai", "猎奇": "Ero Guro", "大学": "College", "3D": "Full CGI", "老师": "Teacher",
}
EN2ZH: dict[str, str] = {}
for _zh, _en in ZH_TAGS.items():
    EN2ZH.setdefault(_en, _zh)
GENRES_FALLBACK = ("Action", "Adventure", "Comedy", "Drama", "Ecchi", "Fantasy", "Hentai", "Horror", "Mahou Shoujo",
                   "Mecha", "Music", "Mystery", "Psychological", "Romance", "Sci-Fi", "Slice of Life", "Sports",
                   "Supernatural", "Thriller")


# ── 输入：图片 / 视频 → 要查的几帧 ─────────────────────────────────────────────────────
def frames(path: Path, count: int, work: Path) -> list[tuple[float | None, bytes]]:
    """→ [(这一帧在原视频里的秒数（图片是 None）, 图片字节)]。"""
    if path.suffix.lower() not in VIDEO_EXT:
        return [(None, path.read_bytes())]
    if not shutil.which("ffmpeg"):
        raise FindError("这是视频 / GIF，要抽帧得装 ffmpeg；没装的话截一张图再来")
    duration = 0.0
    try:
        r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path)],
                           capture_output=True, text=True, timeout=30)
        duration = float((json.loads(r.stdout or "{}").get("format") or {}).get("duration") or 0)
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    times = [round(duration * (i + 0.5) / count, 2) for i in range(count)] if duration > 0.5 else [0.0]
    got = []
    for i, t in enumerate(times):
        out = work / f"frame{i}.jpg"
        try:
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t:.2f}", "-i", str(path), "-frames:v", "1",
                            "-vf", "scale='min(1280,iw)':-2", "-q:v", "3", str(out)], capture_output=True, timeout=90)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.is_file() and out.stat().st_size > 0:
            got.append((t, out.read_bytes()))
    if not got:
        raise FindError("视频里抽不出画面（文件坏了？）")
    return got


# ── trace.moe ─────────────────────────────────────────────────────────────────────
def trace_quota(net: Net) -> int | None:
    try:
        me = net.get(f"{TRACE}/me", timeout=20).json()
        return max(0, int(me.get("quota") or 0) - int(me.get("quotaUsed") or 0))
    except Exception:  # noqa: BLE001
        return None


def trace_search(net: Net, image: bytes) -> list[dict[str, Any]]:
    body, ctype = multipart([], "image", "frame.jpg", image)
    for attempt in range(3):
        try:
            r = net.post(f"{TRACE}/search?anilistInfo&cutBorders", body, headers={"Content-Type": ctype}, timeout=60)
        except NetError as exc:
            if attempt < 1:
                time.sleep(2)
                continue
            raise FindError(f"trace.moe 没连上（{exc}）") from None
        text = r.text()
        if "quota" in text.lower() and r.status != 200:
            raise FindError("trace.moe 今天的次数用完了（免登录每 24 小时 100 次），明天再来")
        if r.status in (402, 429, 503) and attempt < 2:
            time.sleep(3 + attempt * 4)
            continue
        if r.status != 200:
            raise FindError(f"trace.moe 没成（HTTP {r.status}）")
        out = r.json()
        if out.get("error"):
            raise FindError(f"trace.moe：{str(out['error'])[:100]}")
        return [x for x in out.get("result") or [] if isinstance(x, dict)]
    raise FindError("trace.moe 一直在忙，过一会儿再查")


def _episode(v: Any) -> str:
    if v in (None, ""):
        return ""
    if isinstance(v, list):
        return "、".join(_episode(x) for x in v if x not in (None, ""))
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v)


def clock(seconds: Any) -> str:
    try:
        sec = max(0, int(round(float(seconds))))
    except (TypeError, ValueError):
        return ""
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


def vote(per_frame: list[tuple[float | None, list[dict[str, Any]]]]) -> list[dict[str, Any]]:
    """每帧的结果 → 按（AniList 编号, 集数）合起来；先比几帧对上，再比最高相似度。"""
    cands: dict[tuple[Any, str], dict[str, Any]] = {}
    for idx, (clip_at, results) in enumerate(per_frame):
        for r in results[:5]:
            try:
                sim = float(r.get("similarity") or 0)
            except (TypeError, ValueError):
                continue
            if sim < MAYBE:
                continue
            al = r.get("anilist") if isinstance(r.get("anilist"), dict) else {"id": r.get("anilist")}
            key = (al.get("id") or r.get("filename"), _episode(r.get("episode")))
            c = cands.setdefault(key, {"anilist_id": al.get("id"), "anilist": al, "episode": key[1], "similarity": 0.0,
                                       "frames": set()})
            c["frames"].add(idx)
            if sim > c["similarity"]:
                c.update(similarity=sim, start=r.get("from"), end=r.get("to"), clip_at=clip_at, filename=r.get("filename"))
    out = sorted(cands.values(), key=lambda c: (-len(c["frames"]), -c["similarity"]))
    for c in out:
        c["frames"] = len(c["frames"])
    return out


# ── SauceNAO（21 动画 / 22 H-Anime）──────────────────────────────────────────────────
def sauce_anime(net: Net, key: str, image: bytes) -> list[dict[str, Any]]:
    if not key:
        raise FindError("没填 SauceNAO 的 key")
    body, ctype = multipart([], "file", "frame.jpg", image)
    import urllib.parse
    url = SAUCE + "?" + urllib.parse.urlencode([("output_type", "2"), ("numres", "8"), ("dbs[]", "21"), ("dbs[]", "22"),
                                                ("api_key", key)])
    r = net.post(url, body, headers={"Content-Type": ctype}, timeout=40)
    if r.status == 429:
        raise FindError("SauceNAO 今天的次数用完了")
    if r.status != 200:
        raise FindError(f"SauceNAO 没成（HTTP {r.status}）")
    hits = []
    for row in r.json().get("results") or []:
        h, d = row.get("header") or {}, row.get("data") or {}
        try:
            sim, index = float(h.get("similarity") or 0), int(h.get("index_id") or -1)
        except (TypeError, ValueError):
            continue
        title = str(d.get("source") or "").strip()
        if index in (21, 22) and sim >= SAUCE_MIN and title:
            hits.append({"similarity": round(sim / 100, 4), "title": title, "episode": _episode(d.get("part")),
                         "at": str(d.get("est_time") or ""), "adult_index": index == 22})
    return sorted(hits, key=lambda x: -x["similarity"])


# ── AniList ───────────────────────────────────────────────────────────────────────
def anilist(net: Net, query: str, variables: Mapping[str, Any]) -> dict[str, Any]:
    body = json.dumps({"query": query, "variables": dict(variables)}).encode()
    for attempt in range(2):
        try:
            r = net.post(ANILIST, body, headers={"Content-Type": "application/json", "Accept": "application/json"}, timeout=40)
        except NetError as exc:
            raise FindError(f"AniList 没连上（{exc}）") from None
        if r.status == 429 and attempt == 0:
            try:
                wait = int(r.headers.get("retry-after") or 15)
            except ValueError:
                wait = 15
            time.sleep(min(max(wait, 2), 40))
            continue
        out = r.json() if r.body else {}
        if r.status != 200 or out.get("errors"):
            msg = str(((out.get("errors") or [{}])[0] or {}).get("message") or f"HTTP {r.status}")
            raise FindError(f"AniList 没成：{msg[:120]}")
        return out.get("data") or {}
    raise FindError("AniList 限速了（每分钟 30 次），过一分钟再来")


def media_by_ids(net: Net, ids: list[int]) -> dict[int, dict[str, Any]]:
    if not ids:
        return {}
    data = anilist(net, "query($ids:[Int]){Page(perPage:25){media(id_in:$ids,type:ANIME){" + MEDIA_FIELDS + "}}}", {"ids": ids})
    return {m["id"]: m for m in (data.get("Page") or {}).get("media") or [] if isinstance(m, dict) and m.get("id")}


def media_by_title(net: Net, title: str) -> dict[str, Any] | None:
    data = anilist(net, "query($s:String){Page(perPage:1){media(search:$s,type:ANIME){" + MEDIA_FIELDS + "}}}", {"s": title})
    got = (data.get("Page") or {}).get("media") or []
    return got[0] if got else None


def tag_names(net: Net, cache: Path) -> tuple[dict[str, str], dict[str, str]]:
    path = Path(cache) / "anilist_tags.json"
    data: dict[str, Any] = {}
    try:
        if time.time() - path.stat().st_mtime < 7 * 86400:
            data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    if not data.get("tags"):
        try:
            got = anilist(net, "query{MediaTagCollection{name} GenreCollection}", {})
            data = {"tags": [t["name"] for t in got.get("MediaTagCollection") or [] if t.get("name")],
                    "genres": [g for g in got.get("GenreCollection") or [] if g]}
            path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except (FindError, OSError):
            data = {"tags": sorted({v for v in ZH_TAGS.values() if v not in GENRES_FALLBACK}), "genres": list(GENRES_FALLBACK)}
    return {t.lower(): t for t in data.get("tags") or []}, {g.lower(): g for g in data.get("genres") or []}


def titles_of(m: Mapping[str, Any]) -> list[str]:
    t = m.get("title") or {}
    return [str(n) for n in (t.get("native"), t.get("romaji"), t.get("english"), *(m.get("synonyms") or [])) if n]


def is_adult(m: Mapping[str, Any]) -> bool:
    return bool(m.get("isAdult")) or "Hentai" in (m.get("genres") or [])


def hide(m: Mapping[str, Any], flt: Filter) -> str:
    """成人向：红线标签 / 片名 → minor；不管成人向普通番：使用者的「不想看」→ block。"""
    tags = [t["name"] for t in m.get("tags") or [] if isinstance(t, dict) and t.get("name")]
    if is_adult(m) and flt.minor(tags, titles_of(m)):
        return "minor"
    return "block" if flt.disliked(tags, titles_of(m)) else ""


def brief(m: Mapping[str, Any], max_tags: int = 8) -> dict[str, Any]:
    t = m.get("title") or {}
    tags = sorted((x for x in m.get("tags") or [] if isinstance(x, dict) and (x.get("rank") or 0) >= 60),
                  key=lambda x: -(x.get("rank") or 0))
    studios = [n.get("name") for n in ((m.get("studios") or {}).get("nodes") or []) if n.get("name")]
    out = {
        "title": t.get("native") or t.get("romaji") or t.get("english") or "", "romaji": t.get("romaji") or "",
        "year": m.get("seasonYear") or "", "format": FORMAT_ZH.get(str(m.get("format") or ""), m.get("format") or ""),
        "episodes": m.get("episodes") or "", "studio": "、".join(studios[:2]), "adult": is_adult(m),
        "tags": [EN2ZH.get(x["name"], x["name"]) for x in tags[:max_tags]],
        "url": m.get("siteUrl") or (f"https://anilist.co/anime/{m['id']}" if m.get("id") else ""),
        "cover": (m.get("coverImage") or {}).get("large") or "",
    }
    return {k: v for k, v in out.items() if v not in ("", None, [])}


SEARCH_ARGS = {"adult": ("Boolean", "isAdult"), "tags": ("[String]", "tag_in"), "genres": ("[String]", "genre_in"),
               "notTags": ("[String]", "tag_not_in"), "search": ("String", "search"), "sort": ("[MediaSort]", "sort")}


def resolve_terms(terms: list[str], tags: Mapping[str, str], genres: Mapping[str, str]
                  ) -> tuple[list[str], list[str], list[tuple[str, list[str]]]]:
    got_tags, got_genres, unknown = [], [], []
    zh_lower = {k.lower(): v for k, v in ZH_TAGS.items()}
    for term in terms:
        name = ZH_TAGS.get(term) or zh_lower.get(term.lower()) or term
        low = name.lower()
        if low in genres:
            got_genres.append(genres[low])
        elif low in tags:
            got_tags.append(tags[low])
        else:
            pool = list(tags.values()) + list(genres.values()) + list(ZH_TAGS)
            unknown.append((term, difflib.get_close_matches(term, pool, n=5, cutoff=0.5)))
    return list(dict.fromkeys(got_tags)), list(dict.fromkeys(got_genres)), unknown


def anilist_search(net: Net, flt: Filter, cache: Path, *, tags: list[str], exclude: list[str], query: str,
                   adult: bool, sort: str, page: int, limit: int) -> dict[str, Any]:
    tag_map, genre_map = tag_names(net, cache)
    inc_tags, inc_genres, unknown = resolve_terms(tags, tag_map, genre_map)
    exc_tags, exc_genres, unknown_ex = resolve_terms(exclude, tag_map, genre_map)
    if unknown or unknown_ex:
        raise FindError("AniList 上没有这些标签：" + "；".join(
            f"「{t}」" + (f"（相近的：{'、'.join(n)}）" if n else "") for t, n in unknown + unknown_ex) + "。换成相近的，或者当片名搜")
    not_tags = sorted(set(exc_tags) | (set(flt.anilist_not_tags(tag_map.values())) if adult else set()))
    variables = {"page": page, "per": min(limit + 6, 25), "adult": adult, "tags": inc_tags or None,
                 "genres": inc_genres or None, "notTags": not_tags or None, "search": query or None,
                 "sort": [SORTS.get(sort) or ("SEARCH_MATCH" if query else "POPULARITY_DESC")]}
    used = {k: v for k, v in variables.items() if k in SEARCH_ARGS and v not in (None, "", [])}
    decl = "".join(f",${k}:{SEARCH_ARGS[k][0]}" for k in used)
    args = "".join(f",{SEARCH_ARGS[k][1]}:${k}" for k in used)
    gql = (f"query($page:Int,$per:Int{decl}){{Page(page:$page,perPage:$per){{pageInfo{{hasNextPage}}"
           f"media(type:ANIME{args}){{{MEDIA_FIELDS}}}}}}}")
    data = anilist(net, gql, {"page": page, "per": variables["per"], **used})
    page_data = data.get("Page") or {}
    items, withheld = [], {}
    for m in page_data.get("media") or []:
        if not isinstance(m, dict):
            continue
        why = hide(m, flt)
        if why:
            withheld[why] = withheld.get(why, 0) + 1
            continue
        items.append(brief(m))
        if len(items) >= limit:
            break
    label = " · ".join([*(EN2ZH.get(t, t) for t in inc_tags + inc_genres), *([f"「{query}」"] if query else [])]) or "热门"
    return {"items": items, "has_more": bool((page_data.get("pageInfo") or {}).get("hasNextPage")),
            "withheld": withheld, "label": label}


def new_workdir(cache: Path) -> Path:
    work = Path(cache) / f"work_{uuid.uuid4().hex[:10]}"
    work.mkdir(parents=True, exist_ok=True)
    return work


def split_terms(raw: Any) -> list[str]:
    if isinstance(raw, (list, tuple)):
        raw = ",".join(str(x) for x in raw)
    return [t.strip() for t in re.split(r"[,，、;；\n]+", str(raw or "")) if t.strip()]
