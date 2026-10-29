import argparse
import subprocess
import sys
import time
from pathlib import Path

from captions import write_ass
from cards import render_card
from compose import build_timeline, export, save_timeline
from cut import cut
import memes
from minutaje import write_minutaje
from normalize import normalize
from probe import probe
from project import Project, load, trim_ranges
from review import contact_sheet
from transcribe import transcribe
from util import ROOT

REQUIRED_FILTERS = {"ass", "loudnorm", "tile", "drawtext", "drawbox", "overlay", "zscale", "tonemap"}


def check_environment() -> None:
    listed = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    available = {line.split()[1] for line in listed.splitlines() if len(line.split()) > 2}
    missing = REQUIRED_FILTERS - available
    if missing:
        sys.exit(f"Al ffmpeg instalado le faltan filtros: {', '.join(sorted(missing))}")


def step(label: str):
    print(f"→ {label}", flush=True)
    return time.monotonic()


def done(started: float, detail: str = "") -> None:
    print(f"  listo en {time.monotonic() - started:.1f}s {detail}", flush=True)


def clip_kind(spec: dict) -> str:
    if spec.get("meme"):
        return "meme"
    if "freeze" in spec:
        return "freeze"
    if spec.get("card"):
        return "card"
    return "broll" if spec.get("broll") else "speech"


def normalized_clip(project: Project, spec: dict, kind: str, span: list | None) -> Path:
    look = spec.get("look")
    if kind == "meme":
        memes_style = project.style["memes"]
        meme_span = span or [0.0, memes_style["max_seconds"]]
        gain = spec.get("gain_db", memes.gain_for(spec["meme"], memes_style["target_mean_db"]))
        return normalize(project, memes.path_of(spec["meme"]), meme_span, gain, framing="blur", look=look)
    if kind == "freeze":
        sfx = ROOT / "assets/sfx" / f"{spec['sfx']}.wav" if spec.get("sfx") else None
        at = spec["freeze"]
        return normalize(project, project.path(spec["src"]), [at, at + spec["duration"]], spec.get("gain_db", 0.0),
                         look=look, freeze=True, audio_src=sfx)
    if kind == "card":
        return render_card(project, spec)
    gain = spec.get("gain_db", project.style["audio"]["broll_gain_db"] if kind == "broll" else 0.0)
    level = project.style["audio"]["speech_lufs"] if kind == "speech" else None
    return normalize(project, project.path(spec["src"]), span, gain, look=look, level_to=level,
                     level_ranges=trim_ranges(spec.get("trim")))


def normalized_clips(project: Project) -> list:
    fps = project.style["canvas"]["fps"]
    clips = []
    for spec in project.config["clips"]:
        kind = clip_kind(spec)
        ranges = trim_ranges(spec.get("trim"))
        span = [ranges[0][0], ranges[-1][1]] if ranges else None
        path = normalized_clip(project, spec, kind, span)
        keep = [(round((a - span[0]) * fps), round((b - span[0]) * fps)) for a, b in ranges] \
            if len(ranges) > 1 else None
        removed = [(round((a - span[0]) * fps), round((b - span[0]) * fps)) for a, b in spec.get("remove", [])]
        has_own_text = bool(spec.get("nametag") or spec.get("title"))
        clips.append({
            "id": spec["id"],
            "path": path,
            "frames": round(probe(path)["duration"] * fps),
            "keep": keep,
            "remove": removed,
            "kind": kind,
            "silence": spec.get("silence_cut", kind == "speech"),
            "captions": spec.get("captions", kind == "speech" and not has_own_text),
        })
    return clips


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderiza un reel desde projects/<slug>")
    parser.add_argument("project", type=Path)
    parser.add_argument("--preview", action="store_true", help="primeros segundos a baja resolución")
    parser.add_argument("--version", help="escribe build/<slug>.<version>.mp4 en vez de pisar el render principal")
    parser.add_argument("--retranscribe", action="store_true", help="vuelve a transcribir todos los clips (lo anterior queda en previous)")
    args = parser.parse_args()

    check_environment()
    project = load(args.project)

    started = step("normalize")
    clips = normalized_clips(project)
    done(started, f"({len(clips)} clips)")

    started = step("cut")
    cut_path, cut_map = cut(project, clips)
    done(started, f"({len(cut_map['segments'])} segmentos, {cut_map['duration']:.1f}s)")

    started = step("transcribe")
    transcript = transcribe(project, cut_path, cut_map, args.retranscribe)
    done(started)

    started = step("compose")
    timeline = build_timeline(project, cut_path, cut_map, transcript)
    save_timeline(project, timeline)
    write_minutaje(project, cut_map, transcript, timeline)
    ass_path = write_ass(project, timeline, project.build / "subtitles.ass")
    output = export(project, timeline, ass_path, cut_map["key"], args.preview, args.version)
    done(started, f"→ {output}")

    started = step("contact sheet")
    sheet = contact_sheet(project, output)
    done(started, f"→ {sheet}")


if __name__ == "__main__":
    main()
