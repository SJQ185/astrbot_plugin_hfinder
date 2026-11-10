"""筛选：内置红线（固定、不能关）+ 使用者自己的「不想看」（配置里填）。

红线：成人内容里涉及未成年的一律不搜、不列、不报出处——
  · 要搜的词里有这类词 → 不搜；
  · 结果的标签 / 标题 / 简介碰到 → 不列（只说「有几条碰到筛选没列」，不说是什么）；
  · 成人内容核不了标签的 → 先不列（宁可漏，不放过）。
「学生 / 校服 / 学园」这类题材也算在内（高中生是未成年）；「大学生」不算。
这份名单写在代码里、配置里关不掉：插件是拿去给别人用的，这条不放宽。
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# 搜索词、标题、简介里的词（比较前都会做 NFKC + 小写）
MINOR_WORDS_CJK = (
    "萝莉", "蘿莉", "ロリ", "ろり", "正太", "ショタ", "しょた", "幼女", "幼児", "幼儿", "幼兒", "女児", "女童", "男童",
    "儿童", "兒童", "子供", "こども", "童颜", "童顏", "未成年", "小学", "小學", "中学生", "中學生", "初中", "国中", "國中",
    "高中生", "高校生", "女子高生", "女子校生", "女子中学生", "女子小学生", "学生", "學生", "校服", "水手服", "セーラー服",
    "体操服", "體操服", "ブルマ", "死库水", "死庫水", "スク水", "雌小鬼", "メスガキ", "贫乳", "貧乳", "つるぺた", "ランドセル",
    "学园", "學園", "学園", "校园", "校園", "师生", "師生", "スクール", "学校", "學校", "高校", "中学", "中學",
)
MINOR_WORDS_ASCII = (
    "loli", "lolicon", "lolita", "shota", "shotacon", "toddler", "toddlercon", "child", "children", "kid", "kids",
    "underage", "schoolgirl", "schoolgirls", "schoolboy", "school", "student", "students",
    "jk", "jc", "js", "teen", "teens", "mesugaki", "flat chest", "little girl", "elementary", "highschool",
    "kindergarten", "randoseru",
)
# 这些词里含着上面的字，但说的是成年人，先去掉再查
ADULT_OK = ("大学生", "大學生", "女子大生", "女子大学生", "研究生", "留学生", "专门学校", "専門学校", "大学院",
            "university student", "college student")

# E-Hentai / nhentai 的标签（不带命名空间，小写）
MINOR_BOOK_TAGS = frozenset({
    "lolicon", "loli", "shotacon", "shota", "toddlercon", "oppai loli", "low lolicon", "low shotacon", "mesugaki",
    "kindergarten uniform", "randoseru", "school swimsuit", "schoolgirl uniform", "schoolboy uniform",
    "school gym uniform", "gymshorts", "bloomers", "flat chest", "age regression", "child", "teen",
})
EH_EXCLUDE = ("lolicon", "shotacon", "toddlercon", "oppai loli", "mesugaki", "schoolgirl uniform", "school swimsuit",
              "randoseru", "flat chest")
# hanime1 的标签值（站上用繁体）
MINOR_H1_TAGS = frozenset({
    "蘿莉", "正太", "幼女", "雌小鬼", "JK", "學生", "校園", "教室", "保健室", "體育倉庫", "師生", "水手服", "體操服",
    "死庫水", "貧乳", "校服", "制服少女",
})
# AniList 的标签（只对成人向的结果用）
MINOR_ANILIST_TAGS = frozenset({
    "Age Regression", "Boarding School", "Flat Chest", "Kids", "Primarily Child Cast", "Primarily Teen Cast", "School",
    "School Club", "Teens' Love",
})

_ASCII_RE = re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(w) for w in sorted(MINOR_WORDS_ASCII, key=len, reverse=True))
                       + r")(?![a-z0-9])")
_LOWER_H1 = {t.lower() for t in MINOR_H1_TAGS}
_LOWER_AL = {t.lower() for t in MINOR_ANILIST_TAGS}


def norm(text: str) -> str:
    return unicodedata.normalize("NFKC", str(text or "")).lower()


def minor_word(*texts: str) -> str:
    """文字里有没有红线词 → 命中的词（空串 = 没有）。"""
    for raw in texts:
        t = norm(raw)
        if not t:
            continue
        for ok in ADULT_OK:
            t = t.replace(ok, " ")
        for w in MINOR_WORDS_CJK:
            if w in t:
                return w
        m = _ASCII_RE.search(t)
        if m:
            return m.group(1)
    return ""


def _tag_value(tag: str) -> str:
    t = norm(tag).strip()
    return t.split(":", 1)[1].strip() if ":" in t else t


def minor_tag(tags: Iterable[str]) -> str:
    """标签里有没有红线标签（E 站 / N 站 / hanime1 / AniList 的写法都认）→ 命中的标签。"""
    for tag in tags or ():
        v = _tag_value(tag)
        if v in MINOR_BOOK_TAGS or v in _LOWER_H1 or v in _LOWER_AL:
            return str(tag)
    return ""


class Filter:
    def __init__(self, block: Iterable[str] = ()) -> None:
        self.block = [b for b in (norm(x).strip() for x in block or ()) if b]

    # ── 红线 ────────────────────────────────────────────────────────────────
    def query_hit(self, *queries: str) -> str:
        """要搜的词里有红线词 → 原因（这次就不搜）。"""
        word = minor_word(*queries)
        return f"「{word}」这类涉及未成年的词不搜" if word else ""

    def minor(self, tags: Iterable[str] = (), titles: Iterable[str] = (), texts: Iterable[str] = ()) -> bool:
        tags = list(tags or ())
        works = [str(t).split(":", 1)[1] for t in tags if norm(t).startswith("parody:")]     # 原作名（校园作品）也查
        return bool(minor_tag(tags) or minor_word(*[t for t in titles if t], *[t for t in texts if t], *works))

    # ── 使用者自己的「不想看」───────────────────────────────────────────────────
    def disliked(self, tags: Iterable[str] = (), titles: Iterable[str] = ()) -> str:
        if not self.block:
            return ""
        full = {norm(t).strip() for t in tags or ()}
        values = {_tag_value(t) for t in tags or ()}
        blob = " ".join(norm(t) for t in titles or () if t)
        for b in self.block:
            if b in full or b in values or (":" in b and _tag_value(b) in values and b.split(":", 1)[0] in ("tag", "any")):
                return b
            if ":" not in b and len(b) >= 2 and b in blob:
                return b
        return ""

    def hide(self, tags: Iterable[str] = (), titles: Iterable[str] = (), texts: Iterable[str] = ()) -> str:
        """不列的原因：'minor' / 'block' / ''（照列）。"""
        tags = list(tags or ())
        titles = [t for t in titles or () if t]
        if self.minor(tags, titles, texts):
            return "minor"
        if self.disliked(tags, titles):
            return "block"
        return ""

    # ── 搜索时直接让站点排除（结果回来还会再查一遍）───────────────────────────────────
    def eh_exclusions(self) -> str:
        """E 站搜索词后面拼的排除条件（只拼常见的几个，词太长站上会不认；其余靠结果回来再查）。"""
        parts = []
        for name in EH_EXCLUDE:
            q = f'"{name}$"' if " " in name else f"{name}$"
            parts += [f"-female:{q}", f"-male:{q}"]
        for b in self.block:
            if ":" in b and re.fullmatch(r"[a-z]+:[a-z0-9 .'-]+", b):
                ns, v = b.split(":", 1)
                parts.append(f'-{ns}:"{v}$"' if " " in v else f"-{ns}:{v}$")
        return " ".join(parts)

    def nh_exclusions(self) -> str:
        parts = ["-category:western"]
        for name in EH_EXCLUDE:
            parts.append(f'-tag:"{name}"' if " " in name else f"-tag:{name}")
        for b in self.block:
            if re.fullmatch(r"(?:[a-z]+:)?[a-z0-9 .'-]+", b):
                v = _tag_value(b)
                parts.append(f'-tag:"{v}"' if " " in v else f"-tag:{v}")
        return " ".join(parts)

    @staticmethod
    def anilist_not_tags(known: Iterable[str]) -> list[str]:
        """AniList 认得的红线标签（搜成人向时让 AniList 直接排除）。"""
        have = {k.lower(): k for k in known}
        return sorted(have[t.lower()] for t in MINOR_ANILIST_TAGS if t.lower() in have)
