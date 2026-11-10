"""封面拼图：带序号的一张大图，方便在聊天里对着序号挑。没装 Pillow / 一张封面都没拿到就返回空串。"""

from __future__ import annotations

import io
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Mapping

from .net import Net

FONTS = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",          # AstrBot 官方镜像自带
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
    "C:/Windows/Fonts/msyh.ttc",
    "/System/Library/Fonts/PingFang.ttc",
)


def _font(size: int):
    from PIL import ImageFont
    for path in FONTS:
        if Path(path).exists():
            try:
                return ImageFont.truetype(path, size)
            except OSError:
                continue
    return ImageFont.load_default()


def build(net: Net, cards: list[dict], out_dir: Path, header: str = "",
          headers_for: Callable[[str], Mapping[str, str]] | None = None) -> str:
    """cards: [{no, cover, title, meta}] → JPEG 路径。"""
    try:
        from PIL import Image, ImageDraw, ImageOps
    except ImportError:
        return ""
    if not cards:
        return ""

    def fetch(url: str):
        if not url:
            return None
        try:
            r = net.get(url, headers=dict(headers_for(url)) if headers_for else None, timeout=20, limit=5 * 1024 * 1024)
            if r.status != 200:
                return None
            im = Image.open(io.BytesIO(r.body))
            im.load()
            return im.convert("RGB")
        except Exception:  # noqa: BLE001
            return None

    with ThreadPoolExecutor(max_workers=6) as pool:
        thumbs = list(pool.map(fetch, [c.get("cover") or "" for c in cards]))
    if not any(thumbs):
        return ""

    f_num, f_title, f_meta, f_head = _font(22), _font(16), _font(14), _font(20)
    n = len(cards)
    cols = 1 if n == 1 else min(4, n)
    rows = (n + cols - 1) // cols
    card_w, thumb_h, info_h, pad, head_h = 260, 350, 86, 16, 52
    card_h = thumb_h + info_h
    canvas = Image.new("RGB", (pad + cols * (card_w + pad), head_h + pad + rows * (card_h + pad)), (24, 25, 30))
    draw = ImageDraw.Draw(canvas)
    draw.text((pad, 14), header[:60], fill=(235, 238, 245), font=f_head)

    def two_lines(text: str, max_w: int) -> list[str]:
        text = " ".join(str(text or "").split())
        lines, cur = [], ""
        for ch in text:
            if draw.textlength(cur + ch, font=f_title) <= max_w:
                cur += ch
                continue
            lines.append(cur)
            cur = ch
            if len(lines) == 2:
                break
        if len(lines) < 2 and cur:
            lines.append(cur)
        elif len(lines) == 2:
            last = lines[1]
            while last and draw.textlength(last + "…", font=f_title) > max_w:
                last = last[:-1]
            lines[1] = last + "…"
        return lines or ["-"]

    for i, (c, im) in enumerate(zip(cards, thumbs)):
        r, col = divmod(i, cols)
        x0, y0 = pad + col * (card_w + pad), head_h + pad + r * (card_h + pad)
        draw.rounded_rectangle([x0, y0, x0 + card_w, y0 + card_h], radius=10, fill=(36, 38, 46), outline=(58, 62, 74))
        if im is not None:
            fitted = ImageOps.contain(im, (card_w - 8, thumb_h - 8))
            bg = Image.new("RGB", (card_w, thumb_h), (18, 19, 23))
            bg.paste(fitted, ((card_w - fitted.width) // 2, (thumb_h - fitted.height) // 2))
            canvas.paste(bg, (x0, y0))
        else:
            draw.text((x0 + 95, y0 + 160), "无封面", fill=(130, 135, 145), font=f_title)
        badge = f"#{c.get('no', i + 1)}"
        bw = int(draw.textlength(badge, font=f_num)) + 20
        draw.rounded_rectangle([x0 + 8, y0 + 8, x0 + 8 + bw, y0 + 42], radius=8, fill=(220, 55, 80))
        draw.text((x0 + 18, y0 + 11), badge, fill=(255, 255, 255), font=f_num)
        draw.text((x0 + 10, y0 + thumb_h + 6), str(c.get("meta") or "")[:40], fill=(255, 190, 90), font=f_meta)
        for li, line in enumerate(two_lines(c.get("title") or "", card_w - 20)):
            draw.text((x0 + 10, y0 + thumb_h + 28 + li * 22), line, fill=(235, 238, 245), font=f_title)

    out_dir = Path(out_dir) / "grids"
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in sorted(out_dir.glob("*.jpg"))[:-30]:           # 只留最近 30 张
        try:
            old.unlink()
        except OSError:
            pass
    path = out_dir / f"{int(time.time())}_{uuid.uuid4().hex[:6]}.jpg"
    canvas.save(path, "JPEG", quality=88)
    return str(path)
