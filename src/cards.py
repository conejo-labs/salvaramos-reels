import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from project import Project
from util import ROOT, code_signature, digest, ffmpeg, file_signature, is_fresh, seal


def progress(t: float, start: float, length: float) -> float:
    return min(max((t - start) / length, 0.0), 1.0)


def ease_out_cubic(x: float) -> float:
    return 1 - (1 - x) ** 3


def ease_out_back(x: float, overshoot: float = 1.70158) -> float:
    return 1 + (overshoot + 1) * (x - 1) ** 3 + overshoot * (x - 1) ** 2


def svg_aspect(svg: Path) -> float:
    _, _, width, height = (float(v) for v in re.search(r'viewBox="([^"]+)"', svg.read_text()).group(1).split())
    return height / width


def rasterized_logo(project: Project, svg: Path, width: int) -> Image.Image:
    target = project.build / "cards" / f"{svg.stem}_{width}.png"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        height = round(width * svg_aspect(svg))
        ffmpeg("-width", width, "-height", height, "-i", svg, "-frames:v", 1, target)
    return Image.open(target).convert("RGBA")


def text_sprite(spec: dict, max_width: float) -> Image.Image:
    lines = spec["text"].upper().split("\n")
    font_path = str(ROOT / "assets/fonts" / spec["font_file"])
    size = spec["size"]
    font = ImageFont.truetype(font_path, size)
    widest = max(font.getlength(line) for line in lines)
    padding = spec.get("padding", 0)
    if widest + 2 * padding > max_width:
        size = int(size * (max_width - 2 * padding) / widest)
        font = ImageFont.truetype(font_path, size)
        widest = max(font.getlength(line) for line in lines)
    ascent, descent = font.getmetrics()
    line_height = round((ascent + descent) * spec.get("line_spacing", 1.0))
    sprite = Image.new("RGBA", (round(widest + 2 * padding), line_height * len(lines) + 2 * padding), (0, 0, 0, 0))
    draw = ImageDraw.Draw(sprite)
    if spec.get("pill"):
        draw.rounded_rectangle([0, 0, sprite.width - 1, sprite.height - 1], radius=sprite.height // 2, fill=spec["pill"])
    for i, line in enumerate(lines):
        draw.text(((sprite.width - font.getlength(line)) / 2, padding + i * line_height), line, font=font,
                  fill=spec["color"])
    return sprite


def paste_faded(frame: Image.Image, sprite: Image.Image, center: tuple, amount: float, rise: float) -> None:
    if amount <= 0:
        return
    faded = sprite.copy()
    faded.putalpha(sprite.getchannel("A").point(lambda a: round(a * amount)))
    x = round(center[0] - sprite.width / 2)
    y = round(center[1] - sprite.height / 2 + (1 - amount) * rise)
    frame.paste(faded, (x, y), faded)


def hex_rgb(color: str) -> np.ndarray:
    return np.array([int(color[i:i + 2], 16) for i in (1, 3, 5)], dtype=float)


def textured_background(canvas: dict, style: dict) -> Image.Image:
    width, height = canvas["width"], canvas["height"]
    texture = style.get("texture")
    if not texture:
        return Image.new("RGB", (width, height), style["background"])
    rows, cols = np.mgrid[0:height, 0:width]
    distance = np.hypot((cols - width / 2) / (width / 2), (rows - height * style["center_y"]) / (height / 2))
    blend = np.clip(distance, 0, 1)[..., None] ** 1.5
    center, edge = hex_rgb(texture["highlight"]), hex_rgb(style["background"]) * (1 - texture["vignette"])
    return Image.fromarray((center * (1 - blend) + edge * blend).astype(np.uint8))


def pattern_layer(project: Project, canvas: dict, texture: dict) -> tuple[Image.Image, int]:
    mark = rasterized_logo(project, ROOT / texture["pattern"], texture["pattern_size"])
    tint = Image.new("RGBA", mark.size, texture["pattern_color"])
    tint.putalpha(mark.getchannel("A").point(lambda a: round(a * texture["pattern_opacity"])))
    cell = texture["pattern_size"] + texture["pattern_gap"]
    layer = Image.new("RGBA", (canvas["width"] + 2 * cell, canvas["height"] + 2 * cell), (0, 0, 0, 0))
    for row, top in enumerate(range(0, layer.height, cell)):
        shift = cell // 2 if row % 2 else 0
        for left in range(shift, layer.width, cell):
            layer.alpha_composite(tint, (left, top))
    return layer, cell


def drifted(layer: Image.Image, cell: int, canvas: dict, offset: float) -> Image.Image:
    shift = round(offset % cell)
    return layer.crop((cell - shift, cell - shift, cell - shift + canvas["width"], cell - shift + canvas["height"]))


def with_grain(frame: Image.Image, amount: int, rng: np.random.Generator) -> Image.Image:
    pixels = np.asarray(frame, dtype=np.int16)
    noise = rng.integers(-amount, amount + 1, size=pixels.shape[:2] + (1,), dtype=np.int16)
    return Image.fromarray(np.clip(pixels + noise, 0, 255).astype(np.uint8))


def sweep_band(draw: ImageDraw.ImageDraw, width: int, height: int, amount: float, color: str) -> None:
    band = width * 0.35
    left = -band - height * 0.4 + amount * (width + band + height * 0.8)
    draw.polygon([(left, height), (left + band, height), (left + band + height * 0.4, 0), (left + height * 0.4, 0)],
                 fill=color)


def outro_frame(canvas: dict, style: dict, logo: Image.Image, texts: list, backdrop: dict, t: float) -> Image.Image:
    width, height = canvas["width"], canvas["height"]
    frame = backdrop["background"].copy()
    if backdrop["pattern"]:
        layer, cell = backdrop["pattern"]
        marks = drifted(layer, cell, canvas, t * style["texture"]["drift"])
        frame.paste(marks, (0, 0), marks)
    draw = ImageDraw.Draw(frame)
    sweep_band(draw, width, height, ease_out_cubic(progress(t, 0.0, style["sweep_seconds"])), style["accent"])

    pop = progress(t, style["logo_at"], style["pop_seconds"])
    drift = progress(t, style["logo_at"] + style["pop_seconds"], style["duration"])
    scale = ease_out_back(pop) * (1 + style["drift"] * drift) if pop > 0 else 0
    center_x, center_y = width / 2, height * style["center_y"]
    if scale > 0.01:
        size = (max(1, round(logo.width * scale)), max(1, round(logo.height * scale)))
        sprite = logo.resize(size, Image.LANCZOS)
        alpha = sprite.getchannel("A").point(lambda a: round(a * ease_out_cubic(min(1.0, pop * 2))))
        sprite.putalpha(alpha)
        frame.paste(sprite, (round(center_x - size[0] / 2), round(center_y - size[1] / 2)), sprite)

    line = ease_out_cubic(progress(t, style["line_at"], style["line_seconds"])) * logo.width * style["line_width"]
    if line > 1:
        top = center_y + logo.height * (1 + style["drift"]) / 2 + style["line_gap"]
        draw.rectangle([center_x - line / 2, top, center_x + line / 2, top + style["line_thickness"]],
                       fill=style["accent"])
    for spec, sprite in texts:
        amount = ease_out_cubic(progress(t, spec["at"], spec["seconds"]))
        paste_faded(frame, sprite, (center_x, height * spec["center_y"]), amount, style["text_rise"])
    if style.get("texture"):
        frame = with_grain(frame, style["texture"]["grain"], backdrop["rng"])
    return frame


def render_card(project: Project, spec: dict) -> Path:
    canvas = project.style["canvas"]
    style = {**project.style["cards"][spec["card"]], **{k: v for k, v in spec.items() if k == "duration"}}
    svg = ROOT / style["logo"]
    sfx = ROOT / "assets/sfx" / f"{style['sfx']}.wav" if style.get("sfx") else None
    fonts = sorted({spec["font_file"] for spec in style.get("texts", [])})
    pattern = [file_signature(ROOT / style["texture"]["pattern"])] if style.get("texture") else []
    key = digest(style, canvas, file_signature(svg), pattern, [file_signature(ROOT / "assets/fonts" / f) for f in fonts], file_signature(sfx) if sfx else None, code_signature(__file__))
    output = project.build / "cards" / f"{spec['card']}_{key}.mkv"
    if is_fresh(output, key):
        return output
    frames_dir = output.with_suffix("")
    frames_dir.mkdir(parents=True, exist_ok=True)
    logo = rasterized_logo(project, svg, round(canvas["width"] * style["logo_width"]))
    safe = project.style["safe_zone"]
    max_width = canvas["width"] * (1 - 2 * max(safe["left"], safe["right"]))
    texts = [(spec, text_sprite(spec, max_width)) for spec in style.get("texts", [])]
    texture = style.get("texture")
    backdrop = {"background": textured_background(canvas, style),
                "pattern": pattern_layer(project, canvas, texture) if texture else None,
                "rng": np.random.default_rng(7)}
    total = round(style["duration"] * canvas["fps"])
    for index in range(total):
        outro_frame(canvas, style, logo, texts, backdrop, index / canvas["fps"]).save(frames_dir / f"{index:04d}.png")

    audio = ["-i", sfx] if sfx else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    ffmpeg("-framerate", canvas["fps"], "-i", frames_dir / "%04d.png", *audio, "-map", "0:v:0", "-map", "1:a:0",
           "-af", "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,apad",
           "-frames:v", total, "-t", f"{total / canvas['fps']:.6f}",
           "-c:v", "libx264", "-crf", project.style["normalize"]["crf"], "-preset", project.style["normalize"]["preset"],
           "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", output)
    seal(output, key)
    return output
