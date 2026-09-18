#!/usr/bin/env python3
"""Generate istari.ico — Istari medallion (outer cross-frame, ornate band, glowing orb).
Requires: pip install Pillow numpy
"""

import math, os
import numpy as np
from PIL import Image, ImageFilter, ImageDraw


def _to8(a):
    return (np.clip(a, 0.0, 1.0) * 255).astype(np.uint8)


def _gamma(v):
    return np.power(np.clip(v, 0.0, 1.0), 1.0 / 2.2)


def make_frame(size):
    s  = size
    cx = cy = (s - 1) / 2.0

    yy, xx = np.mgrid[0:s, 0:s]
    x = xx.astype(float) - cx
    y = yy.astype(float) - cy
    r = np.sqrt(x * x + y * y)

    # ── Background (near-black, very faint warm tint) ─────────────────────────
    R = np.full((s, s), 0.014)
    G = np.full((s, s), 0.012)
    B = np.full((s, s), 0.010)
    A = np.ones((s, s))

    # ── Central orb glow — amber/gold, white-hot core ─────────────────────────
    orb_r  = s * 0.110
    glow_r = s * 0.195
    halo_r = s * 0.360

    orb_t  = np.clip(1.0 - r / max(orb_r,  0.5), 0.0, 1.0) ** 1.2
    glow_t = np.clip(1.0 - r / max(glow_r, 0.5), 0.0, 1.0) ** 1.8
    halo_t = np.clip(1.0 - r / max(halo_r, 0.5), 0.0, 1.0) ** 2.4

    # amber -> white at the very center
    R += halo_t*0.20 + glow_t*0.52 + orb_t*1.00
    G += halo_t*0.08 + glow_t*0.24 + orb_t*0.82
    B += halo_t*0.01 + glow_t*0.02 + orb_t*0.28

    # Phong specular highlight on orb (upper-left)
    hx_ = cx - orb_r * 0.30
    hy_ = cy - orb_r * 0.34
    h_d = np.sqrt((xx.astype(float) - hx_)**2 + (yy.astype(float) - hy_)**2)
    spec = np.clip(1.0 - h_d / max(orb_r * 0.46, 0.5), 0.0, 1.0) ** 2.5
    spec *= (r < orb_r).astype(float)
    R += spec * 0.28
    G += spec * 0.28
    B += spec * 0.28

    # Bake glow into base image
    base = Image.fromarray(
        np.stack([_to8(_gamma(R)), _to8(_gamma(G)), _to8(_gamma(B)), _to8(A)],
                 axis=-1).astype(np.uint8),
        "RGBA",
    )

    # ── Metalwork layer ───────────────────────────────────────────────────────
    metal = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d     = ImageDraw.Draw(metal)

    lw   = max(1, round(s / 72))   # main structural line width
    lw_t = max(1, round(s / 130))  # thin detail line

    # Colour palette: bronze / gold
    GOLD     = (215, 172,  42, 245)
    GOLD_MID = (168, 130,  26, 228)
    BRONZE   = (108,  78,  14, 210)
    SHINE    = (245, 215, 130, 200)

    # ── 1. Outer frame: thin ring + 4 cross bars ──────────────────────────────
    r_frame = s * 0.456
    d.ellipse(
        [cx - r_frame, cy - r_frame, cx + r_frame, cy + r_frame],
        outline=GOLD, width=lw,
    )

    # Full-diameter cross bars (draw before ornate band so band covers centre)
    bar_end = r_frame * 0.982
    d.line([(cx - bar_end, cy), (cx + bar_end, cy)], fill=GOLD, width=lw)
    d.line([(cx, cy - bar_end), (cx, cy + bar_end)], fill=GOLD, width=lw)

    # Bright dot at each cardinal spoke-end
    dr = max(2, lw + 1)
    for ang in (0, math.pi / 2, math.pi, 3 * math.pi / 2):
        bx = cx + r_frame * math.cos(ang)
        by = cy + r_frame * math.sin(ang)
        d.ellipse([bx - dr, by - dr, bx + dr, by + dr], fill=SHINE)

    # ── 2. Secondary outer ring ───────────────────────────────────────────────
    r_ring2 = s * 0.408
    d.ellipse(
        [cx - r_ring2, cy - r_ring2, cx + r_ring2, cy + r_ring2],
        outline=BRONZE, width=max(1, lw - 1),
    )

    # ── 3. Ornate band (thick filled annulus + engraving marks) ───────────────
    r_band_out = s * 0.340
    r_band_in  = s * 0.272
    r_band_mid = (r_band_out + r_band_in) / 2.0
    band_thick = round(r_band_out - r_band_in) + 1

    # Filled ring body (dark bronze)
    d.ellipse(
        [cx - r_band_mid, cy - r_band_mid, cx + r_band_mid, cy + r_band_mid],
        outline=BRONZE, width=band_thick,
    )
    # Bright border on outer edge
    d.ellipse(
        [cx - r_band_out, cy - r_band_out, cx + r_band_out, cy + r_band_out],
        outline=GOLD_MID, width=lw,
    )
    # Bright border on inner edge
    d.ellipse(
        [cx - r_band_in, cy - r_band_in, cx + r_band_in, cy + r_band_in],
        outline=GOLD_MID, width=lw,
    )

    # Radial engraving ticks inside the band
    n_ticks = max(12, s // 8)
    if s >= 24:
        for i in range(n_ticks):
            ang = i * 2 * math.pi / n_ticks
            r0  = r_band_in  * 1.06
            r1  = r_band_out * 0.94
            d.line(
                [(cx + r0 * math.cos(ang), cy + r0 * math.sin(ang)),
                 (cx + r1 * math.cos(ang), cy + r1 * math.sin(ang))],
                fill=GOLD_MID, width=lw_t,
            )

    # Small highlight dots between major ticks (decorative "studs")
    n_studs = n_ticks // 2
    stud_r  = max(1, lw_t)
    if s >= 48:
        for i in range(n_studs):
            ang  = (i + 0.5) * 2 * math.pi / n_studs
            rmid = r_band_mid
            sx_  = cx + rmid * math.cos(ang)
            sy_  = cy + rmid * math.sin(ang)
            d.ellipse([sx_ - stud_r, sy_ - stud_r,
                       sx_ + stud_r, sy_ + stud_r], fill=GOLD)

    # ── 4. Inner ornate ring (just inside band) ───────────────────────────────
    r_inner = s * 0.228
    d.ellipse(
        [cx - r_inner, cy - r_inner, cx + r_inner, cy + r_inner],
        outline=GOLD, width=lw,
    )

    # ── 5. Orb surround ring ──────────────────────────────────────────────────
    r_orb_ring = s * 0.150
    d.ellipse(
        [cx - r_orb_ring, cy - r_orb_ring, cx + r_orb_ring, cy + r_orb_ring],
        outline=GOLD_MID, width=lw,
    )

    # ── Soften metalwork edges ────────────────────────────────────────────────
    if s >= 32:
        metal = metal.filter(ImageFilter.GaussianBlur(0.45))

    result = Image.alpha_composite(base, metal)

    # ── Circular clip — supersampled for smooth anti-aliased edge ────────────
    result.putalpha(_make_circle_mask(s, s))

    return result


# ── Entry point ───────────────────────────────────────────────────────────────
_ICO_SIZES = [256, 128, 64, 48, 32, 16]   # standard Windows icon sizes


def _make_circle_mask(w, h):
    """4× supersampled circular alpha mask for smooth anti-aliased edges."""
    _SS      = 4
    mask_big = Image.new("L", (w * _SS, h * _SS), 0)
    ImageDraw.Draw(mask_big).ellipse((0, 0, w * _SS - 1, h * _SS - 1), fill=255)
    return mask_big.resize((w, h), Image.LANCZOS)


def _round_existing(path):
    """Read the largest frame from an existing .ico, generate all standard sizes
    with a supersampled circular clip, and overwrite the file."""
    src = Image.open(path)

    # Collect all frames; pick the largest as the high-res source
    raw_frames = []
    i = 0
    while True:
        try:
            src.seek(i)
            raw_frames.append(src.copy().convert("RGBA"))
            i += 1
        except EOFError:
            break

    base = max(raw_frames, key=lambda f: f.width)   # highest-res frame

    frames, szs = [], []
    for s in _ICO_SIZES:
        frame = base.resize((s, s), Image.LANCZOS)
        frame.putalpha(_make_circle_mask(s, s))
        frames.append(frame)
        szs.append((s, s))

    frames[0].save(path, format="ICO", sizes=szs, append_images=frames[1:])


def main():
    # The icon the build actually consumes: Istari.spec (datas/icon) and
    # istari.iss (SetupIconFile) both read the copy in the repository root, so
    # this is where the generator has to write. Writing it under tools/ left the
    # packaged icon untouched — the two copies drifted apart.
    out = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "istari.ico"
    )
    if os.path.exists(out):
        _round_existing(out)
        print(f"istari.ico  circular mask applied  ->  {out}")
        return
    sizes  = [256, 128, 64, 48, 32, 16]
    frames = [make_frame(s) for s in sizes]
    frames[0].save(
        out, format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"istari.ico  ->  {out}")


if __name__ == "__main__":
    main()
