import re
from pathlib import Path

from PIL import Image, ImageDraw

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


def sweep_band(draw: ImageDraw.ImageDraw, width: int, height: int, amount: float, color: str) -> None:
    band = width * 0.35
    left = -band - height * 0.4 + amount * (width + band + height * 0.8)
    draw.polygon([(left, height), (left + band, height), (left + band + height * 0.4, 0), (left + height * 0.4, 0)],
                 fill=color)


def outro_frame(canvas: dict, style: dict, logo: Image.Image, t: float) -> Image.Image:
    width, height = canvas["width"], canvas["height"]
    frame = Image.new("RGB", (width, height), style["background"])
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
    return frame


def render_card(project: Project, spec: dict) -> Path:
    canvas = project.style["canvas"]
    style = {**project.style["cards"][spec["card"]], **{k: v for k, v in spec.items() if k == "duration"}}
    svg = ROOT / style["logo"]
    sfx = ROOT / "assets/sfx" / f"{style['sfx']}.wav" if style.get("sfx") else None
    key = digest(style, canvas, file_signature(svg), file_signature(sfx) if sfx else None, code_signature(__file__))
    output = project.build / "cards" / f"{spec['card']}_{key}.mkv"
    if is_fresh(output, key):
        return output
    frames_dir = output.with_suffix("")
    frames_dir.mkdir(parents=True, exist_ok=True)
    logo = rasterized_logo(project, svg, round(canvas["width"] * style["logo_width"]))
    total = round(style["duration"] * canvas["fps"])
    for index in range(total):
        outro_frame(canvas, style, logo, index / canvas["fps"]).save(frames_dir / f"{index:04d}.png")

    audio = ["-i", sfx] if sfx else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    ffmpeg("-framerate", canvas["fps"], "-i", frames_dir / "%04d.png", *audio, "-map", "0:v:0", "-map", "1:a:0",
           "-af", "aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,apad",
           "-frames:v", total, "-t", f"{total / canvas['fps']:.6f}",
           "-c:v", "libx264", "-crf", project.style["normalize"]["crf"], "-preset", project.style["normalize"]["preset"],
           "-pix_fmt", "yuv420p", "-c:a", "pcm_s16le", output)
    seal(output, key)
    return output
