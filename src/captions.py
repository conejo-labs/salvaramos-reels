import re
from functools import lru_cache
from pathlib import Path

from PIL import ImageFont

from project import Project

SENTENCE_END = (".", "?", "!", "…")
TRAILING_PUNCTUATION = re.compile(r"[,.;:…]+$")


class SafeZoneError(Exception):
    pass


def midpoint(word: dict) -> float:
    return (word["start"] + word["end"]) / 2


def _breaks_page(current: list, word: dict, paging: dict, boundaries: list) -> bool:
    crosses_clip = any(midpoint(current[-1]) < b <= midpoint(word) for b in boundaries)
    return (len(current) >= paging["max_words"]
            or word["end"] - current[0]["start"] > paging["max_duration"]
            or word["start"] - current[-1]["end"] > paging["break_gap"]
            or current[-1]["word"].endswith(SENTENCE_END)
            or word.get("starts_segment", False)
            or crosses_clip)


def paginate(words: list, paging: dict, boundaries: list = ()) -> list:
    groups, current = [], []
    for word in words:
        if current and _breaks_page(current, word, paging, boundaries):
            groups.append(current)
            current = []
        current.append(word)
    if current:
        groups.append(current)

    pages = []
    for k, group in enumerate(groups):
        last_end = group[-1]["end"]
        next_start = groups[k + 1][0]["start"] if k + 1 < len(groups) else None
        holds_until_next = next_start is not None and next_start - last_end <= paging["break_gap"]
        end = next_start if holds_until_next else last_end + paging["tail"]
        clip_end = min((b for b in boundaries if b > midpoint(group[-1])), default=end)
        end = max(min(end, clip_end), last_end)
        pages.append({"start": round(group[0]["start"], 3), "end": round(end, 3), "words": group})
    return pages


def overlaps(page: dict, spans: list) -> bool:
    return any(page["start"] < end and start < page["end"] for start, end in spans)


def word_states(page: dict) -> list:
    words, states = page["words"], []
    for i, word in enumerate(words):
        start = page["start"] if i == 0 else max(word["start"], states[-1][1])
        end = words[i + 1]["start"] if i + 1 < len(words) else page["end"]
        states.append((start, max(end, start + 0.04)))
    return states


def ass_color(hex_rgb: str) -> str:
    r, g, b = hex_rgb[1:3], hex_rgb[3:5], hex_rgb[5:7]
    return f"&H00{b}{g}{r}".upper()


def ass_time(seconds: float) -> str:
    cs = round(seconds * 100)
    return f"{cs // 360000}:{cs // 6000 % 60:02d}:{cs // 100 % 60:02d}.{cs % 100:02d}"


def display(text: str, uppercase: bool) -> str:
    text = text.replace("{", "(").replace("}", ")")
    return text.upper() if uppercase else text


def caption_word(text: str, uppercase: bool) -> str:
    return display(TRAILING_PUNCTUATION.sub("", text), uppercase)


@lru_cache(maxsize=None)
def _font(path: str, pixel_size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(path, pixel_size)


def text_width(font_path: Path, text: str, ass_size: float) -> float:
    ascent, descent = _font(str(font_path), 1000).getmetrics()
    pixel_size = max(1, round(ass_size * 1000 / (ascent + descent)))
    return _font(str(font_path), pixel_size).getlength(text)


class Layout:
    def __init__(self, project: Project):
        canvas, safe = project.style["canvas"], project.style["safe_zone"]
        self.width, self.height = canvas["width"], canvas["height"]
        self.center_x = self.width / 2
        left, right = self.width * safe["left"], self.width * (1 - safe["right"])
        self.max_width = 2 * min(self.center_x - left, right - self.center_x)
        self.max_bottom = self.height * (1 - safe["bottom"])

    def fit(self, width: float) -> float:
        return min(1.0, self.max_width / width)

    def check_bottom(self, center_y: float, block_height: float, what: str) -> None:
        if center_y + block_height / 2 > self.max_bottom:
            raise SafeZoneError(f"{what} invade el {round((1 - self.max_bottom / self.height) * 100)} % inferior")


def scale_tags(scale: float, pop: dict | None = None) -> str:
    final = f"\\fscx{scale * 100:.0f}\\fscy{scale * 100:.0f}"
    if not pop:
        return final
    initial = scale * pop["pop_from"] * 100
    return f"\\fscx{initial:.0f}\\fscy{initial:.0f}\\t(0,{pop['pop_ms']},{final})"


def caption_events(project: Project, pages: list, layout: Layout) -> list:
    style = project.style["captions"]
    font = project.font_file(style["font_file"])
    size, scale, outline = style["size"], style["active_scale"], style["outline"]
    base, active = ass_color(style["color"]), ass_color(style["active_color"])
    center_y = layout.height * style["center_y"]
    layout.check_bottom(center_y, size * scale + 2 * outline, "Los subtítulos")

    pop = project.style["transitions"]
    events = []
    for page in pages:
        texts = [caption_word(w["word"], style["uppercase"]) for w in page["words"]]
        widths = [text_width(font, t, size) for t in texts]
        space = text_width(font, " ", size)
        widest = max(sum(widths) + space * (len(texts) - 1) + widths[i] * (scale - 1) for i in range(len(texts)))
        fit = layout.fit(widest + 2 * outline)
        for i, (start, end) in enumerate(word_states(page)):
            entering = pop if i == 0 else None
            normal = f"\\c{base}&{scale_tags(fit, entering)}"
            big = f"\\c{active}&{scale_tags(fit * scale, entering)}"
            body = " ".join("{" + (big if j == i else normal) + "}" + t for j, t in enumerate(texts))
            prefix = f"{{\\an5\\pos({layout.center_x:.0f},{center_y:.0f})}}"
            events.append((start, end, "caption", prefix + body))
    return events


def text_events(project: Project, texts: list, layout: Layout) -> list:
    pop = project.style["transitions"]
    events = []
    for item in texts:
        style = project.style["texts"][item["style"]]
        lines = [display(line, style["uppercase"]) for line in item["text"].split("\n")]
        if len(lines) > style.get("max_lines", len(lines)):
            raise SafeZoneError(f"El texto '{item['text']}' tiene más de {style['max_lines']} líneas")
        scales = [1.0] + [style.get("secondary_scale", 1.0)] * (len(lines) - 1)
        font = project.font_file(style["font_file"])
        widest = max(text_width(font, line, style["size"] * s) for line, s in zip(lines, scales))
        fit = layout.fit(widest + 2 * style["outline"])
        center_y = layout.height * style["center_y"]
        layout.check_bottom(center_y, sum(scales) * style["size"] * fit, f"El texto '{item['text']}'")
        position = f"\\an5\\pos({layout.center_x:.0f},{center_y:.0f})"
        if item.get("reveal"):
            events += typewriter(item, lines, f"{{{position}\\fscx{fit * 100:.0f}\\fscy{fit * 100:.0f}}}")
            continue
        secondary = ass_color(style.get("secondary_color", style["color"]))
        body = lines[0] + "".join(f"\\N{{\\c{secondary}&{scale_tags(fit * s, pop)}}}{line}"
                                  for line, s in zip(lines[1:], scales[1:]))
        prefix = f"{{{position}{scale_tags(fit, pop)}}}"
        events.append((item["start"], item["end"], item["style"], prefix + body))
    return events


def typewriter(item: dict, lines: list, prefix: str) -> list:
    text = "\n".join(lines)
    letters = [i for i, char in enumerate(text) if not char.isspace()]
    step = item["reveal"] / len(letters)
    events = []
    for k, position in enumerate(letters):
        start = item["start"] + k * step
        end = item["start"] + (k + 1) * step if k + 1 < len(letters) else item["end"]
        shown, hidden = text[:position + 1], text[position + 1:]
        body = shown.replace("\n", "\\N") + "{\\alpha&HFF&}" + hidden.replace("\n", "\\N")
        events.append((round(start, 3), round(end, 3), item["style"], prefix + body))
    return events


def style_line(name: str, style: dict) -> str:
    return (f"Style: {name},{style['font']},{style['size']},{ass_color(style['color'])},{ass_color(style['color'])},"
            f"{ass_color(style['outline_color'])},&H00000000,0,0,0,0,100,100,0,0,1,{style['outline']},0,5,0,0,0,1")


def write_ass(project: Project, timeline: dict, output: Path) -> Path:
    layout = Layout(project)
    events = caption_events(project, timeline["captions"]["pages"], layout) + \
        text_events(project, timeline["texts"], layout)
    styles = [style_line("caption", project.style["captions"])] + \
        [style_line(name, style) for name, style in project.style["texts"].items()]
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {layout.width}", f"PlayResY: {layout.height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "YCbCr Matrix: TV.709", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, "
        "Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, "
        "MarginR, MarginV, Encoding",
        *styles, "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    layer = {"caption": 0}
    for start, end, style, text in sorted(events):
        lines.append(f"Dialogue: {layer.get(style, 1)},{ass_time(start)},{ass_time(end)},{style},,0,0,0,,{text}")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output
