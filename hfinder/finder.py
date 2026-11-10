"""四件事的总入口（AstrBot 壳和测试都只调这里）：

- doujin_search   找本子：关键词 / 标签 / 排行榜 → E 站 + N 站，合并去重
- doujin_source   本子出处：一张图（内页 / 残页 / 截图）→ soutubot → E 站以图搜本 → SauceNAO
- hanime_search   找里番：标签 / 片名 / 分区 / 排行 → hanime1（被拦就退 AniList 资料）
- hanime_source   里番出处：截图 / 短视频 → trace.moe（+ SauceNAO）→ 哪部第几集第几分钟，顺手附 hanime1 播放页

都是同步函数（里面会 sleep 等站点限速），AstrBot 那边放到线程里跑。返回 Found：text 给人 / 模型看，grid 是封面拼图路径。
"""

from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import anime, ehentai, grid, nhentai, soutubot
from .hanime1 import GENRE_ALIASES, H1Down, H1Error, Hanime1, search_url
from .net import Net
from .redline import Filter
from .settings import FindError, NeedVerify, Settings

LANG_ZH = {"chinese": "中文", "japanese": "日文", "english": "英文", "korean": "韩文"}


@dataclass
class Found:
    text: str
    grid: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)


class Finder:
    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg
        self.net = Net(cfg.proxy, cfg.browser_cdp)
        self.flt = Filter(cfg.block)
        self.h1 = Hanime1(self.net, self.flt, cfg.cache)

    @property
    def limit(self) -> int:
        return max(1, min(int(self.cfg.limit or 8), 15))

    # ════════════════════════════════════════════════════════════════════ 找本子
    def doujin_search(self, query: str = "", ranking: str = "", page: int = 1) -> Found:
        query = " ".join(str(query or "").split())[:200]
        if not query and not ranking:
            ranking = "popular"
        why = self.flt.query_hit(query)
        if why:
            raise FindError(why)
        notes: list[str] = []
        withheld: dict[str, int] = {}
        eh_items: list[dict[str, Any]] = []
        nh_items: list[dict[str, Any]] = []
        label = query or ehentai.RANKING_LABELS.get(ranking, ranking)
        try:
            got = ehentai.search(self.net, self.cfg.eh_cookies, self.flt, query=query, ranking=ranking, page=page,
                                 limit=self.limit, language=self.cfg.language)
            eh_items = [ehentai.brief(m, got["site"]) for m in got["items"]]
            _add(withheld, got["withheld"])
            label = got["label"] or label
            has_more = got["has_more"]
        except FindError as exc:
            notes.append(f"E 站：{exc}")
            has_more = False
        if query or not eh_items:
            try:
                sort = {"day": "popular-today", "month": "popular-month"}.get(ranking, "popular")
                got = nhentai.search(self.net, self.flt, query=query, sort=sort, page=page, limit=self.limit,
                                     language=self.cfg.language)
                nh_items = [nhentai.brief(m) for m in got["items"]]
                _add(withheld, got["withheld"])
                has_more = has_more or got["has_more"]
            except FindError as exc:
                notes.append(f"N 站：{exc}")
        items = _merge_books(eh_items, nh_items, self.limit)
        if not items and notes:
            raise FindError("；".join(notes))
        lines = [f"找本子 · {label}" + ("" if items else "：一本都没有。换个词，或者翻下一页试试")]
        for i, it in enumerate(items, 1):
            it["no"] = i
            lines.append(_book_line(it))
        _withheld_note(notes, withheld, "本")
        if has_more and items:
            notes.append(f"还有下一页（第 {page + 1} 页）")
        if notes:
            lines.append("（" + "；".join(notes) + "）")
        g = ""
        if self.cfg.grid and items:
            g = grid.build(self.net, [{"no": it["no"], "cover": it.get("thumb"), "title": it["title"],
                                       "meta": _book_meta(it)} for it in items],
                           self.cfg.cache, header=f"找本子 · {label}", headers_for=self._eh_headers)
        return Found("\n".join(lines), g, items)

    def _eh_headers(self, url: str) -> dict[str, str]:
        if "exhentai.org" in url:
            return {"Cookie": "; ".join(f"{k}={v}" for k, v in self.cfg.eh_cookies.items() if v)}
        return {}

    # ════════════════════════════════════════════════════════════════════ 本子出处
    def doujin_source(self, image: bytes) -> Found:
        notes: list[str] = []
        withheld: dict[str, int] = {}
        cands: list[dict[str, Any]] = []
        used = []
        # 1) soutubot：局部 / 残页最准
        if self.net.has_browser:
            used.append("soutubot")
            try:
                for hit in soutubot.search(self.net, image)[:8]:
                    item = self._verify_soutubot(hit, withheld)
                    if item:
                        cands.append(item)
            except NeedVerify as exc:
                notes.append(str(exc))
            except FindError as exc:
                notes.append(f"soutubot：{exc}")
        # 2) E 站以图搜本：原图整页才对得上
        if not cands:
            used.append("E 站以图搜本")
            try:
                pairs = ehentai.file_search(self.net, image, self.cfg.eh_cookies)
                metas = ehentai.screen(ehentai.by_gid_token(self.net, self.cfg.eh_cookies, pairs[:10]), self.flt, withheld)
                site = ehentai.site_of(self.cfg.eh_cookies)
                cands += [{**ehentai.brief(m, site), "how": "E 站以图搜本（整页对上）"} for m in metas]
            except FindError as exc:
                notes.append(f"E 站：{exc}")
        # 3) SauceNAO：认出本子名，再回 E 站按名字找
        if not cands and self.cfg.saucenao_key:
            used.append("SauceNAO")
            try:
                cands += self._sauce_books(image, withheld)
            except FindError as exc:
                notes.append(f"SauceNAO：{exc}")
        items = _dedupe(cands)[: self.limit]
        _withheld_note(notes, withheld, "条")
        if not items:
            tip = "没找到对得上的本子（试了：" + "、".join(used) + "）。"
            if not self.net.has_browser:
                tip += "内页 / 残页 / 截图最准的是 soutubot.moe，可以自己打开网页上传这张图；"
            tip += "原图整页比截图、压缩过的图好认。"
            return Found(tip + ("（" + "；".join(notes) + "）" if notes else ""))
        lines = ["本子出处（按把握从高到低）："]
        for i, it in enumerate(items, 1):
            it["no"] = i
            lines.append(_book_line(it) + (f"\n    依据：{it['how']}" if it.get("how") else ""))
        if notes:
            lines.append("（" + "；".join(notes) + "）")
        return Found("\n".join(lines), "", items)

    def _verify_soutubot(self, hit: dict[str, Any], withheld: dict[str, int]) -> dict[str, Any] | None:
        """soutubot 只给标题和链接：回 N 站 / E 站取标签核一遍；核不了的不列。"""
        src, ext_id = hit["source"].lower(), hit["id"]
        how = f"soutubot {hit['score']} 分" + (f"，第 {hit['page']} 页" if hit.get("page") else "")
        if self.flt.minor(hit.get("tags") or (), [hit.get("title") or ""]):
            _add(withheld, {"minor": 1})
            return None
        try:
            if "nhentai" in src and ext_id.isdigit():
                meta = nhentai.gallery(self.net, int(ext_id))
                if meta is None:
                    return None
                why = nhentai.hide(meta, self.flt)
                if why:
                    _add(withheld, {why if why != "skip" else "block": 1})
                    return None
                return {**nhentai.brief(meta), "how": how}
            pair = None
            for link in (hit.get("url") or "", hit.get("page_url") or ""):
                m = re.search(r"/g/(\d+)/([0-9a-f]{10})", link)
                if m:
                    pair = (int(m.group(1)), m.group(2))
                    break
                m = re.search(r"/s/([0-9a-f]{10})/(\d+)-(\d+)", link)            # 单页链接：换成整本的
                if m:
                    pair = ehentai.gtoken(self.net, self.cfg.eh_cookies, int(m.group(2)), m.group(1), int(m.group(3)))
                    break
            if ("ehentai" in src or "e-hentai" in src or "exhentai" in src) and pair:
                metas = ehentai.by_gid_token(self.net, self.cfg.eh_cookies, [pair])
                kept = ehentai.screen(metas, self.flt, withheld)
                if kept:
                    return {**ehentai.brief(kept[0], ehentai.site_of(self.cfg.eh_cookies)), "how": how}
                return None
        except FindError:
            pass
        tags = hit.get("tags") or []
        if src not in ("nhentai", "ehentai", "e-hentai", "exhentai") and len(tags) >= 3 and hit.get("url"):
            if self.flt.disliked(tags, [hit.get("title") or ""]):          # 别的站（JM 等）：soutubot 自带的标签够多才算核过
                _add(withheld, {"block": 1})
                return None
            return {"source": src or "soutubot", "id": ext_id, "title": hit.get("title") or f"{src} #{ext_id}",
                    "url": hit["url"], "tags": tags[:12], "how": how}
        _add(withheld, {"unchecked": 1})
        return None

    def _sauce_books(self, image: bytes, withheld: dict[str, int]) -> list[dict[str, Any]]:
        from .net import multipart
        body, ctype = multipart([], "file", "page.jpg", image)
        import urllib.parse
        url = "https://saucenao.com/search.php?" + urllib.parse.urlencode(
            [("output_type", "2"), ("numres", "8"), ("db", "999"), ("api_key", self.cfg.saucenao_key)])
        r = self.net.post(url, body, headers={"Content-Type": ctype}, timeout=40)
        if r.status == 429:
            raise FindError("今天的次数用完了")
        if r.status != 200:
            raise FindError(f"HTTP {r.status}")
        names: list[tuple[float, str]] = []
        for row in r.json().get("results") or []:
            h, d = row.get("header") or {}, row.get("data") or {}
            try:
                sim, idx = float(h.get("similarity") or 0), int(h.get("index_id") or -1)
            except (TypeError, ValueError):
                continue
            if idx in (18, 38) and sim >= 60:
                for k in ("jp_name", "eng_name", "source", "title"):
                    v = str(d.get(k) or "").strip()
                    if v:
                        names.append((sim, v))
                        break
        out: list[dict[str, Any]] = []
        site = ehentai.site_of(self.cfg.eh_cookies)
        for sim, name in names[:3]:
            q = ehentai.core_title(name) or name
            if len(q) < 2 or self.flt.query_hit(q):
                continue
            got = ehentai.search(self.net, self.cfg.eh_cookies, self.flt, query=q, limit=10, language=self.cfg.language)
            _add(withheld, got["withheld"])
            for m in got["items"]:
                score = max(ehentai.similar(name, m.get("title_jpn", "")), ehentai.similar(name, m.get("title", "")))
                if score >= 0.45:
                    out.append({**ehentai.brief(m, site), "how": f"SauceNAO {sim:.0f}% 认出「{name[:40]}」"})
            if out:
                break
        return out

    # ════════════════════════════════════════════════════════════════════ 找里番
    def hanime_search(self, terms: list[str] | None = None, *, tags: list[str] | None = None, query: str = "",
                      genre: str = "", sort: str = "", page: int = 1, exclude: list[str] | None = None) -> Found:
        """terms：指令里空格隔开的一串（自动分出分区 / 排序 / 标签 / 片名）；tags / query：模型分好的。"""
        tags, exclude = list(tags or []), list(exclude or [])
        words: list[str] = []
        for t in terms or []:
            low = t.lower().replace(" ", "")
            if low in GENRE_ALIASES or t in GENRE_ALIASES:
                genre = GENRE_ALIASES.get(t) or GENRE_ALIASES[low]
            elif t in H1_SORT_WORDS:
                sort = H1_SORT_WORDS[t]
            elif t.startswith("-") and len(t) > 1:
                exclude.append(t[1:])
            else:
                words.append(t)
        why = self.flt.query_hit(query, *tags, *words)
        if why:
            raise FindError(why)
        notes: list[str] = []
        try:
            if words:                                        # 认得的当标签，认不得的当片名
                from .hanime1 import resolve_terms
                known, unknown = resolve_terms(words, self.h1.vocab())
                tags += [w for w in words if w not in {u for u, _ in unknown}]
                query = " ".join([query, *(u for u, _ in unknown)]).strip()
            got = self.h1.search(tags=tags, exclude=exclude, query=query, genre=genre, sort=sort, page=page, limit=self.limit)
        except NeedVerify as exc:
            return self._anilist_fallback(tags + words, query, sort, page, str(exc))
        except H1Down as exc:
            return self._anilist_fallback(tags + words, query, sort, page, str(exc))
        items = []
        for i, (pub, cover) in enumerate(got["items"], 1):
            items.append({"no": i, **pub, "cover": cover})
        lines = [f"找里番 · hanime1 · {got['label']}" + ("" if items else "：一部都没有。标签少一两个，或者换个排序 / 翻页")]
        for it in items:
            lines.append(_h1_line(it))
        _withheld_note(notes, got["withheld"], "部")
        if got["has_more"] and items:
            notes.append(f"还有下一页（第 {page + 1} 页）")
        if notes:
            lines.append("（" + "；".join(notes) + "）")
        g = ""
        if self.cfg.grid and items:
            g = grid.build(self.net, [{"no": it["no"], "cover": it["cover"], "title": it.get("title_zh") or it.get("title"),
                                       "meta": " · ".join(x for x in (it.get("subtitles"), it.get("duration")) if x)}
                                      for it in items], self.cfg.cache, header=f"找里番 · {got['label']}")
        return Found("\n".join(lines), g, items)

    def _anilist_fallback(self, words: list[str], query: str, sort: str, page: int, why: str) -> Found:
        """hanime1 用不了：AniList 查资料（片名、年份、标签），每部附一个 hanime1 搜索链接让人自己点开。"""
        tag_map, genre_map = anime.tag_names(self.net, self.cfg.cache)
        inc, gen, unknown = anime.resolve_terms(words, tag_map, genre_map)
        q = " ".join([query, *(u for u, _ in unknown)]).strip()
        got = anime.anilist_search(self.net, self.flt, self.cfg.cache, tags=inc + gen, exclude=[], query=q, adult=True,
                                   sort=sort if sort in anime.SORTS else "", page=page, limit=self.limit)
        items = []
        lines = [f"找里番 · AniList（只有资料）· {got['label']}" + ("" if got["items"] else "：一部都没有")]
        for i, it in enumerate(got["items"], 1):
            it["no"] = i
            it["hanime1_search"] = search_url(it.get("title") or it.get("romaji") or "")
            items.append(it)
            lines.append(f"#{i} {it.get('title', '')}" + (f"（{it['year']}）" if it.get("year") else "")
                         + (f" · {'、'.join(it['tags'][:5])}" if it.get("tags") else "")
                         + f"\n    在 hanime1 上搜：{it['hanime1_search']}")
        notes = [why]
        _withheld_note(notes, got["withheld"], "部")
        lines.append("（" + "；".join(notes) + "）")
        g = ""
        if self.cfg.grid and items:
            g = grid.build(self.net, [{"no": it["no"], "cover": it.get("cover"), "title": it.get("title"),
                                       "meta": str(it.get("year") or "")} for it in items], self.cfg.cache,
                           header=f"找里番 · AniList · {got['label']}")
        return Found("\n".join(lines), g, items)

    # ════════════════════════════════════════════════════════════════════ 里番出处
    def hanime_source(self, path: str | Path, frames: int = 4) -> Found:
        path = Path(path)
        work = anime.new_workdir(self.cfg.cache)
        try:
            left = anime.trace_quota(self.net)
            if left == 0:
                raise FindError("trace.moe 今天的次数用完了（免登录每 24 小时 100 次），明天再来")
            count = max(1, min(frames, 6, left if left is not None else 6))
            shots = anime.frames(path, count, work)
        finally:
            shutil.rmtree(work, ignore_errors=True)
        per_frame, notes = [], []
        for clip_at, img in shots:
            try:
                per_frame.append((clip_at, anime.trace_search(self.net, img)))
            except FindError as exc:
                notes.append(str(exc))
                break
        cands = anime.vote(per_frame)
        sauce: list[dict[str, Any]] = []
        if not any(c["similarity"] >= anime.SURE for c in cands) and self.cfg.saucenao_key:
            try:
                sauce = anime.sauce_anime(self.net, self.cfg.saucenao_key, shots[0][1])[:3]
            except FindError as exc:
                notes.append(f"SauceNAO：{exc}")
        if not cands and not sauce:
            if notes and not per_frame:
                raise FindError(notes[0])
            return Found("没找到对得上的（trace.moe 没有 87% 以上的）。换一张没裁过、字幕少的完整截图，或者给一小段视频；"
                         "太冷门、太老的片可能没收录。真人片查不了。" + ("（" + "；".join(notes) + "）" if notes else ""))
        ids = [int(c["anilist_id"]) for c in cands[:5] if str(c.get("anilist_id") or "").isdigit()]
        media: dict[int, dict[str, Any]] = {}
        try:
            media = anime.media_by_ids(self.net, ids)
        except FindError as exc:
            notes.append(f"{exc}（资料没补全）")
        results, withheld = [], {}
        for c in cands[:5]:
            m = media.get(int(c["anilist_id"])) if str(c.get("anilist_id") or "").isdigit() else None
            al = c.get("anilist") or {}
            if m is None:
                if al.get("isAdult"):
                    _add(withheld, {"unchecked": 1})             # 成人向核不了标签：先不报
                    continue
                m = {"id": al.get("id"), "title": al.get("title") or {"native": c.get("filename") or ""},
                     "synonyms": al.get("synonyms") or [], "isAdult": False}
            why = anime.hide(m, self.flt)
            if why:
                _add(withheld, {why: 1})
                continue
            item = anime.brief(m)
            item.update(similarity=round(c["similarity"], 4), sure=c["similarity"] >= anime.SURE,
                        frames=f"{c['frames']}/{len(per_frame)}", episode=c.get("episode") or "")
            if c.get("start") is not None:
                item["at"] = f"{anime.clock(c['start'])}–{anime.clock(c.get('end'))}"
            results.append(item)
        for s in sauce:
            try:
                m = anime.media_by_title(self.net, s["title"])
            except FindError:
                m = None
            if m is None and s["adult_index"]:
                _add(withheld, {"unchecked": 1})
                continue
            m = m or {"title": {"native": s["title"]}}
            if anime.hide(m, self.flt) or (s["adult_index"] and self.flt.minor((), [s["title"]])):
                _add(withheld, {"minor": 1})
                continue
            item = anime.brief(m)
            item.update(similarity=s["similarity"], sure=s["similarity"] >= 0.9, episode=s.get("episode") or "",
                        at=s.get("at") or "", engine="SauceNAO")
            results.append(item)
        for r in [r for r in results if r.get("adult") and r.get("sure")][:2]:      # 对上的里番去 hanime1 找播放页
            try:
                hit = self.h1.lookup([r.get("title", ""), r.get("romaji", "")], str(r.get("episode") or ""))
            except FindError:
                r["hanime1_search"] = search_url(r.get("title") or "")
                continue
            if hit.get("withheld"):
                results.remove(r)
                _add(withheld, {"minor": 1})
            elif hit.get("links"):
                r["hanime1"] = hit["links"]
        _withheld_note(notes, withheld, "条")
        if not results:
            return Found("对上的结果都碰到了筛选，不报。" + ("（" + "；".join(notes) + "）" if notes else ""))
        lines = ["截图出处（≥90% 基本就是它，87%~90% 只是画面像）："]
        for i, r in enumerate(results, 1):
            r["no"] = i
            head = f"#{i} {r.get('title', '')}" + (f"（{r['romaji']}）" if r.get("romaji") and r.get("romaji") != r.get("title") else "")
            where = " ".join(x for x in (f"第 {r['episode']} 集" if r.get("episode") else "", r.get("at", "")) if x)
            lines.append(f"{head}\n    {round(r['similarity'] * 100)}%" + (f" · {where}" if where else "")
                         + (f" · {r['frames']} 帧对上" if r.get("frames") and r["frames"] != "1/1" else "")
                         + (f" · {r['url']}" if r.get("url") else ""))
            for link in r.get("hanime1") or []:
                lines.append(f"    hanime1：{link['title']}" + (f"（{link['subtitles']}）" if link.get("subtitles") else "")
                             + f" {link['url']}")
            if r.get("hanime1_search"):
                lines.append(f"    在 hanime1 上搜：{r['hanime1_search']}")
        left = anime.trace_quota(self.net)
        if left is not None:
            notes.append(f"trace.moe 今天还剩 {left} 次")
        if notes:
            lines.append("（" + "；".join(notes) + "）")
        return Found("\n".join(lines), "", results)


# ── 指令里的排序词 ─────────────────────────────────────────────────────────────────
H1_SORT_WORDS = {"最新": "uploaded", "最新上传": "uploaded", "新番": "newest", "最新上市": "newest", "热门": "popular",
                 "播放最多": "popular", "好评": "score", "好评最多": "score", "本周": "trending", "本周排行": "trending",
                 "本月": "month", "本月排行": "month", "今日": "today", "本日": "today", "今日排行": "today", "最长": "longest"}
BOOK_RANK_WORDS = {"热门": "popular", "日榜": "day", "昨日": "day", "月榜": "month", "年榜": "year", "总榜": "all"}


def parse_page(words: list[str]) -> tuple[list[str], int]:
    """「第2页」「p2」「2页」→ 页码。"""
    page, rest = 1, []
    for w in words:
        m = re.fullmatch(r"(?:第\s*(\d+)\s*页|p(\d+)|(\d+)页)", w.strip().lower())
        if m:
            page = max(1, min(int(m.group(1) or m.group(2) or m.group(3)), 50))
        else:
            rest.append(w)
    return rest, page


# ── 小工具 ─────────────────────────────────────────────────────────────────────────
def _add(acc: dict[str, int], more: dict[str, int]) -> None:
    for k, v in (more or {}).items():
        acc[k] = acc.get(k, 0) + int(v)


def _withheld_note(notes: list[str], w: dict[str, int], unit: str) -> None:
    parts = []
    if w.get("minor"):
        parts.append(f"涉及未成年 {w['minor']} {unit}（内置红线，不能关）")
    if w.get("block"):
        parts.append(f"你设的「不想看」{w['block']} {unit}")
    if w.get("unchecked"):
        parts.append(f"核不了标签 {w['unchecked']} {unit}")
    if w.get("excluded"):
        parts.append(f"按排除去掉 {w['excluded']} {unit}")
    if parts:
        notes.append("没列出来的：" + "、".join(parts))


def _book_meta(it: dict[str, Any]) -> str:
    bits = [it["source"] if it.get("source") != "nhentai" else "N站", LANG_ZH.get(it.get("language", ""), it.get("language", ""))]
    if it.get("pages"):
        bits.append(f"{it['pages']}P")
    if it.get("rating"):
        bits.append(f"★{it['rating']}")
    elif it.get("favorites"):
        bits.append(f"♥{it['favorites']}")
    return " · ".join(b for b in bits if b)


def _book_line(it: dict[str, Any]) -> str:
    line = f"#{it.get('no', '')} {it.get('title') or it.get('title_en') or ''}\n    {_book_meta(it)} · {it['url']}"
    if it.get("nh_url") and it.get("nh_url") != it.get("url"):
        line += f"\n    N 站同一本：{it['nh_url']}"
    return line


def _h1_line(it: dict[str, Any]) -> str:
    name = it.get("title_zh") or it.get("title") or ""
    meta = " · ".join(x for x in (it.get("subtitles"), "无码" if it.get("uncensored") else "", it.get("duration"),
                                  f"{it['views']}播放" if it.get("views") else "", it.get("date")) if x)
    tags = "、".join((it.get("tags") or [])[:5])
    return f"#{it['no']} {name}\n    {meta}" + (f" · {tags}" if tags else "") + f"\n    {it.get('url', '')}"


def _merge_books(eh: list[dict[str, Any]], nh: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """E 站和 N 站是同一本的并成一条（标上 N 站链接）；N 站独有的穿插进来。"""
    used: set[int] = set()
    for e in eh:
        for n in nh:
            if n["id"] in used:
                continue
            if max(ehentai.similar(e.get("title", ""), n.get("title", "")),
                   ehentai.similar(e.get("title_en", ""), n.get("title_en", ""))) >= 0.6:
                e["nh_url"] = n["url"]
                used.add(n["id"])
                break
    only_nh = [n for n in nh if n["id"] not in used]
    if not eh:
        return only_nh[:limit]
    half = max(1, (limit + 1) // 2)
    out = eh[:half]
    for n in only_nh:
        if len(out) >= limit:
            break
        out.append(n)
    for e in eh[half:]:
        if len(out) >= limit:
            break
        out.append(e)
    return out[:limit]


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen, out = set(), []
    for it in items:
        if it["url"] in seen:
            continue
        seen.add(it["url"])
        out.append(it)
    return out
