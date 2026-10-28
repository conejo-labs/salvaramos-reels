import json
import re
import subprocess
from pathlib import Path

import memes
from captions import overlaps, paginate
from normalize import normalize
from probe import probe
from project import Project
from transcribe import normalize_text, words_of
from util import ffmpeg, is_fresh, read_json, seal, write_json

OVERLAY_STACKING = {"pip": 0, "fullscreen": 1}


def even(value: float) -> int:
    return int(round(value / 2) * 2)


def resolve_point(point, cut_map: dict, words: list, edge: str = "start") -> float:
    if isinstance(point, (int, float)):
        return float(point)
    offset = point.get("offset", 0.0)
    if "clip" in point:
        return cut_map["clips"][point["clip"]][point.get("edge", edge)] + offset
    if "word" in point:
        target, occurrence = normalize_text(point["word"]), point.get("occurrence", 1)
        matches = [w for w in words if normalize_text(w["word"]) == target]
        if len(matches) < occurrence:
            raise ValueError(f"No encuentro «{point['word']}» (ocurrencia {occurrence}) en el transcript")
        return matches[occurrence - 1]["start"] + offset
    raise ValueError(f"Punto de tiempo inválido: {point}")


def resolve_span(spec: dict, cut_map: dict, words: list) -> tuple[float, float]:
    start = resolve_point(spec.get("at", 0.0), cut_map, words)
    if "duration" in spec:
        end = start + spec["duration"]
    elif "until" in spec:
        end = resolve_point(spec["until"], cut_map, words, edge="end")
    elif isinstance(spec.get("at"), dict) and "clip" in spec["at"]:
        end = cut_map["clips"][spec["at"]["clip"]]["end"]
    else:
        raise ValueError(f"Falta duration o until en {spec}")
    return round(start, 3), round(min(end, cut_map["duration"]), 3)


def pip_box(project: Project) -> tuple[int, int]:
    canvas, pip = project.style["canvas"], project.style["pip"]
    return even(canvas["width"] * pip["width"]), even(canvas["height"] * pip["max_height"])


def overlay_rect(kind: str, project: Project, source: Path) -> list:
    width, height = project.style["canvas"]["width"], project.style["canvas"]["height"]
    if kind == "fullscreen":
        return [0, 0, width, height]
    pip, info = project.style["pip"], probe(source)
    return [round(width * pip["left"]), round(height * (1 - pip["bottom"])) - info["height"],
            info["width"], info["height"]]


def resolve_source(project: Project, src: str) -> Path:
    return memes.resolve(src) if memes.is_giphy(src) else project.path(src)


def flash_spans(project: Project, cut_map: dict, overlays: list) -> list:
    transitions = project.style["transitions"]
    length = transitions["flash_frames"] / project.style["canvas"]["fps"]
    starts = {o["start"] for o in overlays if o["type"] == "fullscreen"}
    previous_broll = True
    for clip in sorted(cut_map["clips"].values(), key=lambda c: c["start"]):
        if clip["broll"] and not previous_broll:
            starts.add(clip["start"])
        previous_broll = clip["broll"]
    return [{"start": round(t, 3), "end": round(t + length, 3)} for t in sorted(starts)]


def build_timeline(project: Project, cut_path: Path, cut_map: dict, transcript: dict) -> dict:
    words = words_of(transcript)
    overlays, texts = [], []
    for spec in project.config.get("inserts", []):
        start, end = resolve_span(spec, cut_map, words)
        src_in = spec.get("src_in", 0.0)
        box = pip_box(project) if spec["type"] == "pip" else None
        path = normalize(project, resolve_source(project, spec["src"]), [src_in, src_in + end - start],
                         box=box, loop=spec.get("loop", memes.is_giphy(spec["src"])))
        overlays.append({"type": spec["type"], "src": str(path), "start": start, "end": end,
                         "rect": overlay_rect(spec["type"], project, path), "chroma": spec.get("chroma")})
        if spec.get("text"):
            texts.append({"style": spec.get("text_style", "promo"), "text": spec["text"], "start": start, "end": end})
    for spec in project.config.get("texts", []):
        start, end = resolve_span(spec, cut_map, words)
        texts.append({"style": spec["style"], "text": spec["text"], "start": start, "end": end})

    hidden = [(t["start"], t["end"]) for t in texts if t["style"] == "promo"] \
        if project.style["captions"]["hide_during_promo"] else []
    boundaries = [clip["start"] for clip in cut_map["clips"].values()]
    pages = [p for p in paginate(words, project.style["captions"]["paging"], boundaries) if not overlaps(p, hidden)]
    overlays.sort(key=lambda o: OVERLAY_STACKING[o["type"]])
    return {
        "canvas": project.style["canvas"],
        "duration": cut_map["duration"],
        "base": str(cut_path),
        "overlays": overlays,
        "texts": texts,
        "flashes": flash_spans(project, cut_map, overlays),
        "captions": {"pages": pages},
    }


def measure_loudness(project: Project, source: Path, key: str) -> dict:
    output = project.build / "loudness.json"
    if is_fresh(output, key):
        return read_json(output)
    audio = project.style["audio"]
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostdin", "-i", str(source), "-vn", "-af",
         f"loudnorm=I={audio['loudness']}:TP={audio['true_peak']}:LRA={audio['lra']}:print_format=json",
         "-f", "null", "-"], capture_output=True, text=True, check=True)
    measured = json.loads(re.search(r"\{[^{}]*\}\s*$", result.stderr).group(0))
    write_json(output, measured)
    seal(output, key)
    return measured


def loudnorm_filter(project: Project, measured: dict) -> str:
    audio = project.style["audio"]
    return (f"loudnorm=I={audio['loudness']}:TP={audio['true_peak']}:LRA={audio['lra']}"
            f":measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
            f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
            f":offset={measured['target_offset']}:linear=true")


def chroma_key(chroma: dict | str | None) -> str:
    if not chroma:
        return ""
    settings = chroma if isinstance(chroma, dict) else {"color": chroma}
    color = settings["color"].replace("#", "0x")
    return f",chromakey={color}:{settings.get('similarity', 0.15)}:{settings.get('blend', 0.08)}"


def flash_boxes(flashes: list, transitions: dict) -> str:
    color = transitions["flash_color"].replace("#", "0x")
    return "".join(f",drawbox=x=0:y=0:w=iw:h=ih:t=fill:color={color}@{transitions['flash_opacity']}"
                   f":enable='between(t,{f['start']},{f['end']})'" for f in flashes)


def video_graph(timeline: dict, ass_path: Path, project: Project, preview: dict | None) -> list:
    graph, current = [], "0:v"
    for k, overlay in enumerate(timeline["overlays"], start=1):
        x, y, w, h = overlay["rect"]
        start, end = overlay["start"], overlay["end"]
        graph.append(f"[{k}:v]setpts=PTS-STARTPTS+{start}/TB,scale={w}:{h}{chroma_key(overlay.get('chroma'))}[ov{k}]")
        graph.append(f"[{current}][ov{k}]overlay={x}:{y}:eof_action=pass:enable='between(t,{start},{end})'[base{k}]")
        current = f"base{k}"
    flashes = flash_boxes(timeline["flashes"], project.style["transitions"])
    tail = f",scale={preview['width']}:{preview['height']}:flags=lanczos" if preview else ""
    graph.append(f"[{current}]null{flashes},ass=filename='{ass_path}':fontsdir='{project.fonts_dir}'{tail}[vout]")
    return graph


def export(project: Project, timeline: dict, ass_path: Path, cut_key: str, preview: bool) -> Path:
    settings = project.style["export"]
    preview_settings = project.style["preview"] if preview else None
    measured = measure_loudness(project, Path(timeline["base"]), cut_key)
    graph = video_graph(timeline, ass_path, project, preview_settings)
    graph.append(f"[0:a]{loudnorm_filter(project, measured)},aresample={settings['sample_rate']}[aout]")
    inputs = ["-i", timeline["base"]]
    for overlay in timeline["overlays"]:
        inputs += ["-i", overlay["src"]]
    output = project.build / (f"{project.slug}.preview.mp4" if preview else f"{project.slug}.mp4")
    limit = ["-t", preview_settings["seconds"]] if preview else []
    ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", "[vout]", "-map", "[aout]", *limit,
           "-r", project.style["canvas"]["fps"], "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
           "-crf", settings["crf"], "-preset", preview_settings["preset"] if preview else settings["preset"],
           "-c:a", "aac", "-b:a", settings["audio_bitrate"], "-ar", settings["sample_rate"],
           "-movflags", "+faststart", output)
    return output


def save_timeline(project: Project, timeline: dict) -> Path:
    path = project.build / "timeline.json"
    write_json(path, timeline)
    return path
