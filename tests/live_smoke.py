"""连真站点的冒烟测试（手动跑，会真的去搜）：python tests/live_smoke.py [book|h|hsrc]
只打印条数、来源、链接里的站点，不打印标题（测试时不看内容）。"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from hfinder.finder import Finder  # noqa: E402
from hfinder.settings import FindError, Settings  # noqa: E402


def show(found, label):
    hosts = [it.get("url", "").split("/")[2] if "://" in it.get("url", "") else "-" for it in found.items]
    print(f"[{label}] items={len(found.items)} grid={'yes' if found.grid else 'no'} hosts={hosts}")
    tail = [ln for ln in found.text.splitlines() if ln.startswith("（")]
    print("   note:", tail[-1][:300] if tail else "-")


def main():
    which = sys.argv[1:] or ["book", "h", "hsrc"]
    cfg = Settings(data_dir=Path(tempfile.mkdtemp()), saucenao_key=os.environ.get("SAUCENAO_KEY", ""),
                   proxy=os.environ.get("HF_PROXY", ""), browser_cdp=os.environ.get("HF_CDP", ""), limit=6)
    f = Finder(cfg)
    if "book" in which:
        try:
            show(f.doujin_search("女仆 中文"), "找本子 女仆 中文")
        except FindError as exc:
            print("[找本子] error:", exc)
        try:
            show(f.doujin_search("", "popular"), "找本子 热门")
        except FindError as exc:
            print("[找本子 热门] error:", exc)
        try:
            f.doujin_search("萝莉")
            print("[红线] ✗ 没拦住")
        except FindError as exc:
            print("[红线] ok:", exc)
    if "h" in which:
        try:
            show(f.hanime_search(["女仆"]), "找里番 女仆")
        except FindError as exc:
            print("[找里番] error:", exc)
    if "hsrc" in which and len(sys.argv) > 2:
        try:
            show(f.hanime_source(sys.argv[2]), "里番出处")
        except FindError as exc:
            print("[里番出处] error:", exc)


if __name__ == "__main__":
    main()
