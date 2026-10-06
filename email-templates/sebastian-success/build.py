"""Build the Sebastian Success email assets.

Renders:
  out/hero.gif     animated deep-space banner (twinkling stars, logo, title)
  out/divider.gif  animated starlight divider line
  out/sig.png      handwritten-style signature

Usage:  python3 build.py ["Script line on the banner"]
Needs Pillow, numpy and ffmpeg; gifsicle (optional) shrinks the GIFs. Fonts (all SIL OFL) are fetched once into ./fonts.
"""
import math
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

HERE = os.path.dirname(os.path.abspath(__file__))
FONTS = os.path.join(HERE, "fonts")
OUT = os.path.join(HERE, "out")
LOGO = os.path.join(HERE, "assets", "logo.webp")

FONT_URLS = {
    "Cinzel.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/cinzel/Cinzel%5Bwght%5D.ttf",
    "CormorantItalic.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/cormorantgaramond/CormorantGaramond-Italic%5Bwght%5D.ttf",
    "Signature.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/herrvonmuellerhoff/HerrVonMuellerhoff-Regular.ttf",
}

W, H = 1120, 560          # hero rendered at 2x, shown at 560x280
FRAMES = 24
FRAME_MS = 90
HERO_OUT_W = 840        # 1.5x of the 560px display width; keeps the GIF small enough to embed
BRAND_BLUE = (5, 102, 255)


def font(name, size, weight=None):
    path = os.path.join(FONTS, name)
    if not os.path.exists(path):
        os.makedirs(FONTS, exist_ok=True)
        urllib.request.urlretrieve(FONT_URLS[name], path)
    f = ImageFont.truetype(path, size)
    if weight is not None:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def spaced_text(draw, cx, y, text, fnt, fill, tracking):
    """Draw centered text with extra letter spacing."""
    widths = [draw.textlength(ch, font=fnt) for ch in text]
    total = sum(widths) + tracking * (len(text) - 1)
    x = cx - total / 2
    for ch, w in zip(text, widths):
        draw.text((x, y), ch, font=fnt, fill=fill, anchor="ls")
        x += w + tracking


def soft_noise(rng, h, w, scale):
    small = rng.random((max(2, h // scale), max(2, w // scale)))
    img = Image.fromarray((small * 255).astype(np.uint8)).resize((w, h), Image.BICUBIC)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(scale / 2)), dtype=np.float32) / 255


def space_background(rng):
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    base = np.zeros((H, W, 3), np.float32)
    # deep navy -> near black vertical gradient
    t = yy / H
    base += np.stack([4 + 6 * (1 - t), 8 + 10 * (1 - t), 22 + 28 * (1 - t)], -1)
    # nebula clouds: blue and violet, kept faint so text stays crisp
    n1 = soft_noise(rng, H, W, 110) * soft_noise(rng, H, W, 70)
    n2 = soft_noise(rng, H, W, 140) * soft_noise(rng, H, W, 80)
    base += n1[..., None] * np.array([10, 60, 170], np.float32) * 0.9
    base += n2[..., None] * np.array([90, 30, 140], np.float32) * 0.7
    # glow behind the logo
    d = np.sqrt(((xx - W / 2) / 260) ** 2 + ((yy - 190) / 200) ** 2)
    base += np.exp(-d ** 2)[..., None] * np.array([10, 45, 120], np.float32)
    # vignette
    v = np.sqrt(((xx - W / 2) / (W * 0.7)) ** 2 + ((yy - H / 2) / (H * 0.8)) ** 2)
    base *= np.clip(1.15 - v * 0.55, 0.45, 1)[..., None]
    return base


def star_sprite(radius, cross):
    size = int(radius * 8) | 1
    c = size // 2
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) - c
    r = np.sqrt(xx ** 2 + yy ** 2)
    core = np.exp(-(r / radius) ** 2)
    if cross:
        arm = radius * 3.6
        spikes = (np.exp(-(xx / 0.9) ** 2) * np.exp(-np.abs(yy) / arm) +
                  np.exp(-(yy / 0.9) ** 2) * np.exp(-np.abs(xx) / arm))
        core = np.maximum(core, spikes * 0.85)
    return core


def add_sprite(img, x, y, sprite, color, amp):
    s = sprite.shape[0]
    c = s // 2
    x0, y0 = int(round(x)) - c, int(round(y)) - c
    xs0, ys0 = max(0, -x0), max(0, -y0)
    xs1, ys1 = min(s, W - x0), min(s, H - y0)
    if xs0 >= xs1 or ys0 >= ys1:
        return
    patch = sprite[ys0:ys1, xs0:xs1, None] * np.array(color, np.float32) * amp
    img[y0 + ys0:y0 + ys1, x0 + xs0:x0 + xs1] += patch


def flare(f, start, dur):
    """0 outside a star's flare window, a smooth 0->1->0 bump inside it (wraps around the loop)."""
    p = (f - start) % FRAMES
    return math.sin(math.pi * (p + 1) / (dur + 1)) ** 2 if p < dur else 0.0


def load_logo(size):
    logo = Image.open(LOGO).convert("RGBA")
    logo = logo.crop(logo.getbbox())
    logo.thumbnail((size, size), Image.LANCZOS)
    return logo


def build_hero(script_line):
    rng = np.random.default_rng(7)
    bg = space_background(rng)

    # static dust: many faint pinpoints
    for _ in range(900):
        x, y = rng.random() * W, rng.random() * H
        b = rng.random() ** 3 * 120 + 25
        add_sprite(bg, x, y, star_sprite(0.6, False), (b * 0.85, b * 0.9, b), 1)

    star_colors = [(255, 255, 255), (190, 215, 255), (255, 236, 205), (170, 200, 255)]
    twinklers = []
    for _ in range(150):
        twinklers.append(dict(
            x=rng.random() * W, y=rng.random() * H,
            r=0.7 + rng.random() * 0.9,
            col=star_colors[rng.integers(len(star_colors))],
            base=0.3 + rng.random() * 0.3,
            amp=0.6 + rng.random() * 0.6,
            start=int(rng.integers(FRAMES)), dur=int(rng.integers(4, 7))))
    sparkles = []
    for _ in range(16):
        sparkles.append(dict(
            x=rng.random() * W, y=rng.random() * H,
            r=1.3 + rng.random() * 0.8,
            col=star_colors[rng.integers(len(star_colors))],
            start=int(rng.integers(FRAMES)), dur=8))
    # keep the brightest sparkles clear of the text block
    sparkles = [s for s in sparkles if not (280 < s["y"] < 500 and 120 < s["x"] < W - 120)]

    # logo with a soft brand-blue halo and a thin light rim
    logo = load_logo(230)
    lx, ly = (W - logo.width) // 2, 190 - logo.height // 2
    alpha = logo.split()[3]
    halo = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    glow = Image.new("RGBA", logo.size, (60, 140, 255, 255))
    glow.putalpha(alpha)
    halo.paste(glow, (lx, ly), glow)
    halo = halo.filter(ImageFilter.GaussianBlur(14))
    rim = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rimc = Image.new("RGBA", logo.size, (200, 225, 255, 255))
    rimc.putalpha(alpha.filter(ImageFilter.MaxFilter(5)))
    rim.paste(rimc, (lx, ly), rimc)
    rim = rim.filter(ImageFilter.GaussianBlur(1.5))
    logo_arr = np.asarray(logo, np.float32)

    # text layer (static)
    text = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(text)
    title_f = font("Cinzel.ttf", 64, weight=600)
    sub_f = font("Cinzel.ttf", 20, weight=500)
    script_f = font("CormorantItalic.ttf", 36, weight=500)
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    spaced_text(sd, W / 2, 392, "SEBASTIAN SUCCESS", title_f, (0, 0, 0, 220), 14)
    shadow = shadow.filter(ImageFilter.GaussianBlur(6))
    spaced_text(td, W / 2, 390, "SEBASTIAN SUCCESS", title_f, (246, 248, 255, 255), 14)
    spaced_text(td, W / 2, 438, "FROM THE DESK OF SEBASTIAN", sub_f, (196, 210, 240, 255), 9)
    td.line([(W / 2 - 70, 466), (W / 2 + 70, 466)], fill=(120, 160, 230, 200), width=2)
    td.text((W / 2, 515), script_line, font=script_f, fill=(232, 236, 250, 255), anchor="ms")

    frames = []
    for f in range(FRAMES):
        t = f / FRAMES
        img = bg.copy()
        for s in twinklers:
            a = s["base"] + s["amp"] * flare(f, s["start"], s["dur"])
            add_sprite(img, s["x"], s["y"], star_sprite(s["r"], False), s["col"], a)
        for s in sparkles:
            a = 0.2 + 0.9 * flare(f, s["start"], s["dur"])
            add_sprite(img, s["x"], s["y"], star_sprite(s["r"] * (0.8 + 0.5 * a), True), s["col"], a)
        # shooting star across the upper right, frames 4..12
        st = (f - 4) / 8
        if 0 <= st <= 1:
            hx, hy = 760 + 300 * st, 40 + 110 * st
            for i in range(150):     # dense samples so the trail reads as one streak
                fade = (1 - i / 150) ** 1.5 * math.sin(math.pi * st)
                add_sprite(img, hx - i * 1.4, hy - i * 0.51, star_sprite(0.8, False),
                           (230, 240, 255), fade * 0.45)
            add_sprite(img, hx, hy, star_sprite(1.4, True), (255, 255, 255), math.sin(math.pi * st))

        frame = Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)).convert("RGBA")
        frame = Image.alpha_composite(frame, halo)
        frame = Image.alpha_composite(frame, rim)

        # glint sweeping across the logo, frames 14..21
        la = logo_arr.copy()
        gt = (f - 14) / 7
        if 0 <= gt <= 1:
            yy, xx = np.mgrid[0:logo.height, 0:logo.width].astype(np.float32)
            band = (xx + yy * 0.6) - (gt * (logo.width + logo.height * 0.6 + 120) - 60)
            g = np.exp(-(band / 26) ** 2)[..., None]
            la[..., :3] = la[..., :3] + (255 - la[..., :3]) * g * 0.75
        frame.alpha_composite(Image.fromarray(la.astype(np.uint8)), (lx, ly))

        frame = Image.alpha_composite(frame, shadow)
        frame = Image.alpha_composite(frame, text)
        frames.append(frame.convert("RGB").resize((HERO_OUT_W, HERO_OUT_W // 2), Image.LANCZOS))
    return frames


def build_divider():
    w, h = 900, 27     # 1.5x of the 600x18 display size
    rng = np.random.default_rng(3)
    xs = np.linspace(0, 1, w)
    pts = [(int(40 + rng.random() * (w - 80)), 0.7 + rng.random() * 0.8, int(rng.integers(FRAMES)))
           for _ in range(14)]
    frames = []
    for f in range(FRAMES):
        t = f / FRAMES
        img = np.full((h, w, 3), 255, np.float32)
        # brand blue -> violet -> brand blue line, fading at the ends
        col = np.stack([5 + 120 * np.sin(math.pi * xs), 102 - 40 * np.sin(math.pi * xs),
                        255 - 20 * np.sin(math.pi * xs)], -1)
        ends = np.clip(np.minimum(xs, 1 - xs) * 8, 0, 1)
        glint = np.exp(-((xs - t * 1.3 + 0.15) / 0.05) ** 2)
        for dy, a in ((0, 0.95), (1, 0.55), (-1, 0.55), (2, 0.15), (-2, 0.15)):
            row = h // 2 + dy
            mix = (a * ends)[:, None]
            img[row] = img[row] * (1 - mix) + col * mix
            img[row] = img[row] + (255 - img[row]) * (glint[:, None] * a * 0.9)
        # tiny four-point sparkles that pulse along the line
        for x, r, start in pts:
            a = flare(f, start, 8)
            if a == 0:
                continue
            spr = star_sprite(r, True)
            s = spr.shape[0]
            c = s // 2
            y0, x0 = h // 2 - c, x - c
            ys0, xs0 = max(0, -y0), max(0, -x0)
            ys1, xs1 = min(s, h - y0), min(s, w - x0)
            patch = spr[ys0:ys1, xs0:xs1, None] * a
            region = img[y0 + ys0:y0 + ys1, x0 + xs0:x0 + xs1]
            region[:] = region * (1 - patch) + np.array([40, 90, 230], np.float32) * patch
        frames.append(Image.fromarray(np.clip(img, 0, 255).astype(np.uint8)))
    return frames


def build_signature():
    """Ink on white (the signature always sits on the white card), quantized to keep it tiny."""
    f = font("Signature.ttf", 120)
    img = Image.new("RGB", (900, 170), (255, 255, 255))
    d = ImageDraw.Draw(img)
    d.text((34, 112), "Sebastian Success", font=f, fill=(18, 48, 140), anchor="ls")
    box = ImageOps.invert(img).getbbox()
    img = img.crop((box[0] - 4, box[1] - 4, box[2] + 4, box[3] + 4))
    return img.quantize(colors=24, method=Image.Quantize.MEDIANCUT)


def write_gif(frames, path, lossy=60):
    tmp = tempfile.mkdtemp()
    try:
        for i, fr in enumerate(frames):
            fr.save(os.path.join(tmp, f"f{i:03d}.png"))
        fps = 1000 / FRAME_MS
        pattern = os.path.join(tmp, "f%03d.png")
        palette = os.path.join(tmp, "palette.png")
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", pattern,
                        "-vf", "palettegen=max_colors=256:stats_mode=full", palette], check=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-framerate", str(fps), "-i", pattern,
                        "-i", palette, "-lavfi",
                        "paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle",
                        "-loop", "0", path], check=True)
        if shutil.which("gifsicle"):
            subprocess.run(["gifsicle", "-O3", f"--lossy={lossy}", "-b", path], check=True)
    finally:
        shutil.rmtree(tmp)


def main():
    script_line = sys.argv[1] if len(sys.argv) > 1 else "Let's get 'er done, feller · October 6, 2026"
    os.makedirs(OUT, exist_ok=True)
    hero = build_hero(script_line)
    write_gif(hero, os.path.join(OUT, "hero.gif"))
    hero[0].save(os.path.join(OUT, "hero-still.png"))
    write_gif(build_divider(), os.path.join(OUT, "divider.gif"))
    build_signature().save(os.path.join(OUT, "sig.png"), optimize=True)
    for n in ("hero.gif", "divider.gif", "sig.png"):
        print(n, os.path.getsize(os.path.join(OUT, n)) // 1024, "KB")


if __name__ == "__main__":
    main()
