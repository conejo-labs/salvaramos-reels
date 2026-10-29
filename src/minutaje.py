from pathlib import Path

from project import Project, trim_ranges
from transcribe import words_of


def mmss(seconds: float) -> str:
    return f"{int(seconds // 60):02d}:{seconds % 60:04.1f}"


def spoken_in(words: list, start: float, end: float) -> str:
    return " ".join(w["word"] for w in words if start <= (w["start"] + w["end"]) / 2 < end)


def clip_content(spec: dict, words: list, span: dict) -> str:
    if spec.get("nametag"):
        return "Presentación: " + spec["nametag"].replace("\n", " · ")
    if spec.get("title"):
        return "Pregunta: " + spec["title"].replace("\n", " ")
    if spec.get("meme"):
        return f"Meme: {spec['meme']}"
    if "freeze" in spec:
        return f"Congelado {spec['duration']} s" + (f" + {spec['sfx']}" if spec.get("sfx") else "")
    if spec.get("card"):
        return "Cortina con el logo"
    if spec.get("broll"):
        return "b-roll"
    return spoken_in(words, span["start"], span["end"])


def source_name(spec: dict) -> str:
    if spec.get("meme"):
        return f"memes/{spec['meme']}"
    if spec.get("card"):
        return f"cortina/{spec['card']}"
    return Path(spec["src"]).name


def raw_ranges(spec: dict) -> str:
    if "freeze" in spec:
        return f"frame {mmss(spec['freeze'])}"
    ranges = trim_ranges(spec.get("trim"))
    return " + ".join(f"{mmss(a)}–{mmss(b)}" for a, b in ranges) if ranges else "completo"


def covering(timeline: dict, span: dict) -> list:
    tolerance = 0.01
    return [Path(o["src"]).stem.rsplit("_", 1)[0] for o in timeline["overlays"]
            if o["type"] == "fullscreen" and o["start"] < span["end"] - tolerance
            and span["start"] < o["end"] - tolerance]


def write_minutaje(project: Project, cut_map: dict, transcript: dict, timeline: dict) -> Path:
    words = words_of(transcript, cut_map, project.config.get("transcription", {}).get("corrections", []))
    speed = timeline["speed"]
    lines = [f"# Minutaje — {project.config.get('title', project.slug)}", "",
             f"Duración del reel: {mmss(cut_map['duration'] / speed)} (a {speed}×). «Raw» son segundos del archivo "
             "original (lo que va en `trim`); «Reel» es el tiempo en el video final, ya sin silencios y acelerado.", "",
             "| Reel | Clip | Raw | Tramo del raw | Qué se dice / qué es | Tapado por |",
             "|---|---|---|---|---|---|"]
    for spec in project.config["clips"]:
        span = cut_map["clips"][spec["id"]]
        cover = ", ".join(covering(timeline, span))
        lines.append(f"| {mmss(span['start'] / speed)}–{mmss(span['end'] / speed)} | {spec['id']} | "
                     f"`{source_name(spec)}` | "
                     f"{raw_ranges(spec)} | {clip_content(spec, words, span).replace('|', '/')} | {cover} |")
    output = project.dir / "minutaje.md"
    output.write_text("\n".join(lines) + "\n")
    return output
