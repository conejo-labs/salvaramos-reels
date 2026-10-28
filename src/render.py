import argparse
import subprocess
import sys
import time
from pathlib import Path

from captions import write_ass
from compose import build_timeline, export, save_timeline
from cut import auto_editor_bin, cut
from minutaje import write_minutaje
from normalize import normalize
from probe import probe
from project import Project, load, trim_ranges
from review import contact_sheet
from transcribe import StaleTranscript, transcribe

REQUIRED_FILTERS = {"ass", "loudnorm", "tile", "drawtext", "drawbox", "overlay", "zscale", "tonemap"}


def check_environment() -> None:
    listed = subprocess.run(["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True).stdout
    available = {line.split()[1] for line in listed.splitlines() if len(line.split()) > 2}
    missing = REQUIRED_FILTERS - available
    if missing:
        sys.exit(f"Al ffmpeg instalado le faltan filtros: {', '.join(sorted(missing))}")
    if not auto_editor_bin():
        sys.exit("No encuentro auto-editor: instala requirements.txt en el venv")


def step(label: str):
    print(f"→ {label}", flush=True)
    return time.monotonic()


def done(started: float, detail: str = "") -> None:
    print(f"  listo en {time.monotonic() - started:.1f}s {detail}", flush=True)


def normalized_clips(project: Project) -> list:
    fps, broll_gain = project.style["canvas"]["fps"], project.style["audio"]["broll_gain_db"]
    clips = []
    for spec in project.config["clips"]:
        broll = spec.get("broll", False)
        ranges = trim_ranges(spec.get("trim"))
        span = [ranges[0][0], ranges[-1][1]] if ranges else None
        path = normalize(project, project.path(spec["src"]), span,
                         spec.get("gain_db", broll_gain if broll else 0.0))
        keep = [(round((a - span[0]) * fps), round((b - span[0]) * fps)) for a, b in ranges] \
            if len(ranges) > 1 else None
        has_own_text = bool(spec.get("nametag") or spec.get("title"))
        clips.append({
            "id": spec["id"],
            "path": path,
            "frames": round(probe(path)["duration"] * fps),
            "keep": keep,
            "silence": spec.get("silence_cut", not broll),
            "captions": spec.get("captions", not (broll or has_own_text)),
            "broll": broll,
        })
    return clips


def main() -> None:
    parser = argparse.ArgumentParser(description="Renderiza un reel desde projects/<slug>")
    parser.add_argument("project", type=Path)
    parser.add_argument("--preview", action="store_true", help="primeros segundos a baja resolución")
    parser.add_argument("--retranscribe", action="store_true", help="reemplaza transcript.json (deja respaldo)")
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
    try:
        transcript = transcribe(project, cut_path, cut_map, args.retranscribe)
    except StaleTranscript as stale:
        sys.exit(str(stale))
    done(started)

    started = step("compose")
    timeline = build_timeline(project, cut_path, cut_map, transcript)
    save_timeline(project, timeline)
    write_minutaje(project, cut_map, transcript, timeline)
    ass_path = write_ass(project, timeline, project.build / "subtitles.ass")
    output = export(project, timeline, ass_path, cut_map["key"], args.preview)
    done(started, f"→ {output}")

    started = step("contact sheet")
    sheet = contact_sheet(project, output)
    done(started, f"→ {sheet}")


if __name__ == "__main__":
    main()
