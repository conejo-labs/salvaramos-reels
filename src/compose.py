import json
import re
import subprocess
from pathlib import Path

from captions import overlaps, paginate
from normalize import normalize
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


def overlay_rect(kind: str, project: Project) -> list:
    width, height = project.style["canvas"]["width"], project.style["canvas"]["height"]
    if kind == "fullscreen":
        return [0, 0, width, height]
    pip = project.style["pip"]
    w = even(width * pip["width"])
    h = even(w * height / width)
    return [round(width * pip["left"]), round(height * (1 - pip["bottom"])) - h, w, h]


def build_timeline(project: Project, cut_path: Path, cut_map: dict, transcript: dict) -> dict:
    words = words_of(transcript)
    overlays, texts = [], []
    for spec in project.config.get("inserts", []):
        start, end = resolve_span(spec, cut_map, words)
        src_in = spec.get("src_in", 0.0)
        path = normalize(project, project.path(spec["src"]), [src_in, src_in + end - start])
        overlays.append({"type": spec["type"], "src": str(path), "start": start, "end": end,
                         "rect": overlay_rect(spec["type"], project)})
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


def video_graph(timeline: dict, ass_path: Path, fonts_dir: Path, preview: dict | None) -> list:
    graph, current = [], "0:v"
    for k, overlay in enumerate(timeline["overlays"], start=1):
        x, y, w, h = overlay["rect"]
        start, end = overlay["start"], overlay["end"]
        graph.append(f"[{k}:v]setpts=PTS-STARTPTS+{start}/TB,scale={w}:{h}[ov{k}]")
        graph.append(f"[{current}][ov{k}]overlay={x}:{y}:eof_action=pass:enable='between(t,{start},{end})'[base{k}]")
        current = f"base{k}"
    tail = f",scale={preview['width']}:{preview['height']}:flags=lanczos" if preview else ""
    graph.append(f"[{current}]ass=filename='{ass_path}':fontsdir='{fonts_dir}'{tail}[vout]")
    return graph


def export(project: Project, timeline: dict, ass_path: Path, cut_key: str, preview: bool) -> Path:
    settings = project.style["export"]
    preview_settings = project.style["preview"] if preview else None
    measured = measure_loudness(project, Path(timeline["base"]), cut_key)
    graph = video_graph(timeline, ass_path, project.fonts_dir, preview_settings)
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
