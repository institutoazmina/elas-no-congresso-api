"""Parliamentarian OG image renderer (Pillow port of the site's Satori/Sharp renderer)."""

import io
import math
from dataclasses import dataclass
from functools import cache
from pathlib import Path

import numpy as np
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

ASSETS = Path(__file__).parent / "assets"
NAME_FONT = ASSETS / "Anybody-Bold-Width75.ttf"
BODY_FONT = ASSETS / "PlusJakartaSans-SemiBold.ttf"

WIDTH, HEIGHT = 1200, 630
INK = (0x0B, 0x0F, 0x5E, 255)
FAVORABLE = (0xC1, 0xE6, 0x39, 255)
UNFAVORABLE = (0xFF, 0x58, 0x65, 255)
NEUTRAL = (0x77, 0x77, 0xE8, 255)
PORTRAIT_BG = (0x26, 0x26, 0x9E, 255)
BORDER = (0x99, 0x8D, 0x96)

PORTRAIT_X, PORTRAIT_Y, PORTRAIT_W, PORTRAIT_H = 496, 70, 208, 277
NAME_TOP, NAME_SIZE = 367, 50
AFFILIATION_TOP, AFFILIATION_SIZE = 425, 28
ROW_X, ROW_Y, ICON = 275, 489, 54
BAR_X, BAR_Y, BAR_W, BAR_H = 349, 506, 502, 20


@dataclass(frozen=True)
class OgData:
    name: str
    affiliation: str
    favorable: int
    unfavorable: int
    portrait: bytes | None


class _Font:
    """Pillow font plus the GPOS pair kerning Satori (opentype.js) applies."""

    def __init__(self, path: Path, size: int):
        self.size = size
        self.pil = ImageFont.truetype(str(path), size)
        tt = TTFont(path)
        self.scale = size / tt["head"].unitsPerEm
        self.cmap = tt.getBestCmap()
        self.hmtx = tt["hmtx"]
        self.pairs = (
            [
                sub
                for lookup in tt["GPOS"].table.LookupList.Lookup
                if lookup.LookupType == 2
                for sub in lookup.SubTable
            ]
            if "GPOS" in tt
            else []
        )
        ascent, descent = self.pil.getmetrics()
        self.ascent, self.descent = ascent, descent

    def _kerning(self, left: str, right: str) -> int:
        for sub in self.pairs:
            if left not in sub.Coverage.glyphs:
                continue
            if sub.Format == 1:
                index = sub.Coverage.glyphs.index(left)
                for record in sub.PairSet[index].PairValueRecord:
                    if record.SecondGlyph == right:
                        return getattr(record.Value1, "XAdvance", 0) or 0
            else:
                c1 = sub.ClassDef1.classDefs.get(left, 0)
                c2 = sub.ClassDef2.classDefs.get(right, 0)
                value = sub.Class1Record[c1].Class2Record[c2].Value1
                kern = getattr(value, "XAdvance", 0) or 0
                if kern:
                    return kern
        return 0

    def layout(self, text: str) -> tuple[list[tuple[str, float]], float]:
        glyphs = [self.cmap.get(ord(ch), ".notdef") for ch in text]
        x, placed = 0.0, []
        for i, (ch, glyph) in enumerate(zip(text, glyphs, strict=True)):
            placed.append((ch, x))
            advance = self.hmtx[glyph][0]
            if i + 1 < len(glyphs):
                advance += self._kerning(glyph, glyphs[i + 1])
            x += advance * self.scale
        return placed, x

    def baseline(self, top: float) -> float:
        return top + (self.size - (self.ascent + self.descent)) / 2 + self.ascent


@cache
def _font(path: Path, size: int) -> _Font:
    return _Font(path, size)


def _centered_text(draw: ImageDraw.ImageDraw, text: str, font: _Font, top: float, fill) -> None:
    placed, width = font.layout(text)
    start = WIDTH / 2 - width / 2
    y = font.baseline(top)
    for ch, x in placed:
        draw.text((start + x, y), ch, font=font.pil, fill=fill, anchor="ls")


def _vips_lanczos3_reduce(img: np.ndarray, shrink: float, axis: int) -> np.ndarray:
    """Exact port of libvips reduceh/reducev (lanczos3, uchar fixed point) used by sharp."""
    size = img.shape[axis]
    out_size = int(math.floor(size / shrink + 0.5))
    n = 2 * int(np.rint(3 * shrink)) + 1
    offset = (1 + out_size * shrink - size) / 2.0 - 1

    def sinc(v: float) -> float:
        return 1.0 if v == 0 else math.sin(v * math.pi) / (v * math.pi)

    def lanczos3(x: float) -> float:
        return sinc(x) * sinc(x / 3) if -3 <= x <= 3 else 0.0

    masks = []
    for t in range(65):
        half = float(np.float32(t) / np.float32(64)) + n / 2.0 - 1
        coeffs = [lanczos3((i - half) / shrink) for i in range(n)]
        total = sum(coeffs)
        masks.append([int(c / total * 4096) for c in coeffs])
    masks = np.array(masks, dtype=np.int64)

    pad = math.ceil(n / 2.0) - 1
    src = np.moveaxis(img, axis, 0)
    padded = src[np.clip(np.arange(-pad, size + n - pad), 0, size - 1)]
    out = np.empty((out_size,) + src.shape[1:], dtype=np.int64)
    for o in range(out_size):
        pos = (o + 0.5) * shrink - 0.5 - offset
        p = int(pos)
        t = (((int(pos * 128)) & 127) + 1) >> 1
        acc = np.tensordot(masks[t], padded[p : p + n], axes=(0, 0))
        out[o] = np.clip((acc + 2048) >> 12, 0, 255)
    return np.moveaxis(out, 0, axis)


def _portrait(data: bytes) -> Image.Image:
    """sharp.resize(208, 277, {fit: 'cover', position: 'north'})."""
    src = Image.open(io.BytesIO(data)).convert("RGB")
    shrink = min(src.width / PORTRAIT_W, src.height / PORTRAIT_H)
    if shrink < 1:
        # Foto menor que o retrato: o sharp amplia com bicúbica, não com o reduce.
        src = src.resize((round(src.width / shrink), round(src.height / shrink)), Image.BICUBIC)
        shrink = 1.0
    arr = np.asarray(src).astype(np.int64)
    if shrink > 1:
        arr = _vips_lanczos3_reduce(arr, shrink, 0)
        arr = _vips_lanczos3_reduce(arr, shrink, 1)
    h, w = arr.shape[:2]
    left = (w - PORTRAIT_W + 1) // 2
    return Image.fromarray(arr[:PORTRAIT_H, left : left + PORTRAIT_W].astype(np.uint8), "RGB")


def _composite(background: Image.Image, layer: Image.Image) -> Image.Image:
    """libvips 'over' composite (float32, fused multiply-add), as sharp.composite does."""
    f = np.float32
    base = np.asarray(background.convert("RGBA")).astype(f) / f(255)
    over = np.asarray(layer).astype(f) / f(255)
    base_alpha, over_alpha = base[..., 3:4].copy(), over[..., 3:4].copy()
    base = base * base_alpha
    base[..., 3:4] = base_alpha
    over = over * over_alpha
    alpha = over_alpha + base_alpha * (f(1) - over_alpha)
    # A soma em float64 seguida de arredondamento imita o FMA do libvips.
    out = (
        over.astype(np.float64) + (f(1) - over_alpha).astype(np.float64) * base.astype(np.float64)
    ).astype(f)
    out = np.where(alpha == 0, f(0), out / np.where(alpha == 0, f(1), alpha))
    out[..., 3:4] = alpha
    return Image.fromarray(np.clip(out * f(255), 0, 255).astype(np.uint8), "RGBA")


def _border(layer: Image.Image) -> Image.Image:
    """1.5px inner border: full outer pixel, half-covered inner pixel (pixman OVER rounding)."""
    arr = np.asarray(layer).astype(np.int64).copy()
    region = arr[PORTRAIT_Y : PORTRAIT_Y + PORTRAIT_H, PORTRAIT_X : PORTRAIT_X + PORTRAIT_W]
    coverage = np.zeros(region.shape[:2], dtype=np.int64)
    coverage[1, 1:-1] = coverage[-2, 1:-1] = coverage[1:-1, 1] = coverage[1:-1, -2] = 128
    for y, x in [(1, 1), (1, -2), (-2, 1), (-2, -2)]:
        coverage[y, x] = 191
    coverage[0, :] = coverage[-1, :] = coverage[:, 0] = coverage[:, -1] = 255

    def div255(v):
        return (v + 128 + ((v + 128) >> 8)) >> 8

    a = coverage[..., None]
    rgb = div255(np.array(BORDER) * a) + div255(region[..., :3] * (255 - a))
    region[..., :3] = np.where(a > 0, rgb, region[..., :3])
    return Image.fromarray(arr.astype(np.uint8), "RGBA")


def render(data: OgData) -> bytes:
    layer = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    # Portrait (or initials) with a 1.5px inner border.
    box = (PORTRAIT_X, PORTRAIT_Y, PORTRAIT_X + PORTRAIT_W - 1, PORTRAIT_Y + PORTRAIT_H - 1)
    draw.rectangle(box, fill=PORTRAIT_BG)
    if data.portrait:
        layer.paste(_portrait(data.portrait), (PORTRAIT_X, PORTRAIT_Y))
    else:
        initials = "".join(word[0] for word in data.name.split()[:2])
        font = _font(BODY_FONT, 64)
        draw.text(
            (PORTRAIT_X + PORTRAIT_W / 2, PORTRAIT_Y + PORTRAIT_H / 2),
            initials,
            font=font.pil,
            fill=(255, 255, 255, 255),
            anchor="mm",
        )
    layer = _border(layer)
    draw = ImageDraw.Draw(layer)

    _centered_text(draw, data.name.upper(), _font(NAME_FONT, NAME_SIZE), NAME_TOP, INK)
    _centered_text(
        draw,
        data.affiliation or "Partido/UF não informados",
        _font(BODY_FONT, AFFILIATION_SIZE),
        AFFILIATION_TOP,
        INK,
    )

    # Favorability bar between the thumbs.
    rated = data.favorable + data.unfavorable
    draw.rectangle(
        (BAR_X, BAR_Y, BAR_X + BAR_W - 1, BAR_Y + BAR_H - 1),
        fill=(255, 255, 255, 255) if rated else NEUTRAL,
    )
    if rated:
        separator = 4 if data.favorable and data.unfavorable else 0
        segment = BAR_W - separator
        favorable_w = round(segment * data.favorable / rated)
        unfavorable_w = segment - favorable_w
        if favorable_w:
            draw.rectangle(
                (BAR_X, BAR_Y, BAR_X + favorable_w - 1, BAR_Y + BAR_H - 1), fill=FAVORABLE
            )
        if unfavorable_w:
            start = BAR_X + favorable_w + separator
            draw.rectangle(
                (start, BAR_Y, start + unfavorable_w - 1, BAR_Y + BAR_H - 1), fill=UNFAVORABLE
            )
    layer.alpha_composite(Image.open(ASSETS / "thumbs-up.png").convert("RGBA"), (ROW_X, ROW_Y))
    layer.alpha_composite(
        Image.open(ASSETS / "thumbs-down.png").convert("RGBA"), (ROW_X + 650 - ICON, ROW_Y)
    )

    out = io.BytesIO()
    _composite(Image.open(ASSETS / "og-background.png"), layer).save(out, "PNG")
    return out.getvalue()
