"""离线单测（不连网）：python -m unittest discover -s tests"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hfinder import ehentai, finder, hanime1, nhentai, redline  # noqa: E402
from hfinder.redline import Filter  # noqa: E402


class RedLine(unittest.TestCase):
    def setUp(self):
        self.f = Filter()

    def test_query_words(self):
        for q in ("萝莉", "loli", "JK 制服", "女子高生", "中学生", "school uniform", "ロリ巨乳", "学生", "雌小鬼", "ＪＫ"):
            self.assertTrue(self.f.query_hit(q), q)
        for q in ("女仆 中文", "female:maid", "大学生", "jkt48 ではない", "修女", "精灵", "OL", "人妻", "teacher"):
            self.assertFalse(self.f.query_hit(q), q)

    def test_tags_all_sites(self):
        self.assertTrue(self.f.minor(["female:lolicon"]))
        self.assertTrue(self.f.minor(["tag:schoolgirl uniform"]))
        self.assertTrue(self.f.minor(["蘿莉"]))
        self.assertTrue(self.f.minor(["Primarily Teen Cast"]))
        self.assertTrue(self.f.minor([], ["(C99) [サークル] JK と放課後"]))
        self.assertTrue(self.f.minor([], [], ["彼女は女子校生"]))
        self.assertTrue(self.f.minor([], ["(Cレヴォ35) [サークル] 前夜祭 (スクールランブル) [中国翻訳]"]))   # 11-10 真机漏过的
        self.assertTrue(self.f.minor(["parody:school rumble", "female:maid"], ["前夜祭"]))
        self.assertFalse(self.f.minor(["parody:genshin impact"], ["Schooner 号の冒険"]))
        self.assertFalse(self.f.minor(["female:maid", "female:elf", "female:bunny girl"], ["メイドさん"]))
        self.assertFalse(self.f.minor(["female:small breasts"]))          # 小胸不等于未成年

    def test_user_block(self):
        f = Filter(["male:yaoi", "NTR", "netorare"])
        self.assertEqual(f.hide(tags=["male:yaoi"]), "block")
        self.assertEqual(f.hide(tags=["NTR"]), "block")
        self.assertEqual(f.hide(tags=["female:netorare"]), "block")
        self.assertEqual(f.hide(tags=["female:maid"]), "")
        self.assertEqual(f.hide(tags=["female:lolicon", "male:yaoi"]), "minor")     # 红线先算

    def test_exclusions(self):
        f = Filter(["male:yaoi"])
        ex = f.eh_exclusions()
        self.assertIn("-female:lolicon$", ex)
        self.assertIn('-female:"schoolgirl uniform$"', ex)
        self.assertIn("-male:yaoi$", ex)
        self.assertIn("-tag:lolicon", f.nh_exclusions())
        self.assertEqual(Filter.anilist_not_tags(["School", "Maids", "Primarily Teen Cast"]), ["Primarily Teen Cast", "School"])


class EHentai(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(ehentai.normalize_query("女仆 精灵"), "female:maid female:elf")
        self.assertEqual(ehentai.normalize_query("female:bunny girl"), 'female:"bunny girl"')
        self.assertEqual(ehentai.core_title("(C97) [サークル (作者)] 本の名前 (原作) [中国翻訳]"), "本の名前")

    def test_galleries_and_screen(self):
        page = '<a href="https://e-hentai.org/g/123/abcdef0123/">x</a><a href="https://e-hentai.org/g/123/abcdef0123/">'
        self.assertEqual(ehentai.galleries(page), [(123, "abcdef0123")])
        metas = [{"gid": 1, "token": "a" * 10, "title": "ok", "tags": ["female:maid"], "category": "Doujinshi"},
                 {"gid": 2, "token": "b" * 10, "title": "bad", "tags": ["female:lolicon"], "category": "Doujinshi"},
                 {"gid": 3, "token": "c" * 10, "title": "west", "tags": [], "category": "Western"}]
        w = {}
        kept = ehentai.screen(metas, Filter(), w)
        self.assertEqual([m["gid"] for m in kept], [1])
        self.assertEqual(w, {"minor": 1})


class NHentai(unittest.TestCase):
    def test_meta_and_hide(self):
        item = {"id": 5, "title": {"english": "Maid", "japanese": "メイド"}, "num_pages": 20, "tag_ids": [1, 2]}
        m = nhentai.to_meta(item, {1: {"type": "tag", "name": "maid"}, 2: {"type": "language", "name": "chinese"}})
        self.assertEqual(m["tags"], ["tag:maid", "language:chinese"])
        self.assertEqual(nhentai.hide(m, Filter()), "")
        self.assertEqual(nhentai.language_of(m), "chinese")
        unknown = nhentai.to_meta(item, {})
        self.assertEqual(nhentai.hide(unknown, Filter()), "minor")       # 标签没取到：先不列
        self.assertIn("language:chinese", nhentai.normalize_query("女仆"))


def card(vid, title, cover="https://x/c.jpg"):
    return (f'<a href="https://hanime1.me/watch?v={vid}"><img src="{cover}"><div class="home-rows-videos-title">{title}</div>'
            f'<div class="duration">12:34</div></a>')


def watch(vid, original, zh, tags):
    tag_html = "".join(f'<a href="/search?tags%5B%5D={v}">{l}<span>({n})</span></a>' for v, l, n in tags)
    return (f'<html><head><meta property="og:title" content="{original} - Hanime1.me">'
            f'<meta property="og:description" content="{zh} - あらすじ"><meta name="keywords" content="{tags[0][0] if tags else ""}">'
            f'</head><body><h3 id="shareBtn-title">{original}</h3><a id="video-artist-name" href="#">スタジオ</a>'
            f'<div class="video-description-panel"><div>觀看次數：12.3萬次 2026-11-01</div></div>{tag_html}</body></html>')


class FakeNet:
    has_browser = False


class Hanime1Tests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.h1 = hanime1.Hanime1(FakeNet(), Filter(["NTR"]), self.tmp)
        self.pages = {
            "/watch?v=1": watch(1, "メイドさん", "女仆小姐", [("女僕", "女仆", 9), ("中文字幕", "中文字幕", 5)]),
            "/watch?v=2": watch(2, "放課後", "放学后", [("JK", "JK", 9)]),
            "/watch?v=3": watch(3, "寝取られ", "NTR", [("NTR", "NTR", 9)]),
        }
        self.h1.get_many = lambda paths: {p: self.pages[p] for p in paths if p in self.pages}

    def test_parse(self):
        cards = hanime1.parse_cards(card(1, "女仆小姐") + card(2, "x"))
        self.assertEqual([c["id"] for c in cards], ["1", "2"])
        w = hanime1.parse_watch("1", self.pages["/watch?v=1"])
        self.assertTrue(w["chinese_subs"])
        self.assertIn("女僕", w["_values"])
        self.assertEqual(w["views"], "12.3萬次")

    def test_screen(self):
        cards = [{"id": str(i), "title_zh": f"t{i}", "cover": ""} for i in (1, 2, 3, 4)]
        items, withheld = self.h1._screen(cards, 8, set(), {"女僕": "女仆"})
        self.assertEqual([p["url"] for p, _ in items], ["https://hanime1.me/watch?v=1"])
        self.assertEqual(withheld, {"minor": 1, "block": 1, "unchecked": 1})

    def test_resolve_terms(self):
        pairs = [("女僕", "女仆"), ("絲襪", "丝袜"), ("妖精", "妖精"), ("巫女", "巫女")]
        got, unknown = hanime1.resolve_terms(["女仆", "白丝", "精灵", "巫女", "不存在"], pairs)
        self.assertEqual(got, ["女僕", "絲襪", "妖精", "巫女"])
        self.assertEqual(unknown[0][0], "不存在")


class Soutubot(unittest.TestCase):
    def test_parse(self):
        from hfinder import soutubot
        data = {"results": [
            {"score": 20, "path_segments": [{"source_key": "nhentai", "external_id": "1"}]},
            {"score": 74.6, "path_segments": [{"source_key": "nhentai", "external_id": "660528", "page_no": 177,
                                               "metadata": {"title": {"primary": "本"}, "tags": ["succubus"]},
                                               "links": {"page_url": "https://nhentai.net/g/660528/177/"}}]},
            {"score": 60, "source_key": "ehentai", "external_id": "9", "metadata": {"title": {"pretty": "E 本"}},
             "links": {"page_url": "https://e-hentai.org/s/0123456789/9-3"}},
        ]}
        got = soutubot.parse(data)
        self.assertEqual([(g["source"], g["id"], g["page"]) for g in got], [("nhentai", "660528", 177), ("ehentai", "9", None)])
        self.assertEqual(got[1]["title"], "E 本")
        self.assertIn("/s/0123456789/9-3", got[1]["page_url"])


class FinderBits(unittest.TestCase):
    def test_merge_books(self):
        eh = [{"id": 1, "title": "[A] 本の名前", "title_en": "[A] Book", "url": "e1"},
              {"id": 2, "title": "別の本", "title_en": "Other", "url": "e2"}]
        nh = [{"id": 9, "title": "[A] 本の名前 [中国翻訳]", "title_en": "[A] Book [Chinese]", "url": "n9"},
              {"id": 8, "title": "N だけ", "title_en": "Only N", "url": "n8"}]
        out = finder._merge_books(eh, nh, 8)
        self.assertEqual([x["url"] for x in out], ["e1", "e2", "n8"])          # E 站占前一半，N 站独有的补在后面
        self.assertEqual([x["url"] for x in finder._merge_books(eh * 3, nh, 4)][:2], ["e1", "e2"])
        self.assertEqual(out[0]["nh_url"], "n9")

    def test_parse_page(self):
        self.assertEqual(finder.parse_page(["女仆", "第3页"]), (["女仆"], 3))
        self.assertEqual(finder.parse_page(["p2", "修女"]), (["修女"], 2))

    def test_withheld_note(self):
        notes = []
        finder._withheld_note(notes, {"minor": 2, "block": 1}, "本")
        self.assertIn("涉及未成年 2 本", notes[0])


if __name__ == "__main__":
    unittest.main()
