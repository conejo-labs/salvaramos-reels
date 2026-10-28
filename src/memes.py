import argparse
import sys
from functools import lru_cache
from pathlib import Path

import yaml

from minutaje import mmss, spoken_in
from project import load
from transcribe import words_of
from util import ROOT, ffmpeg, read_json

CATALOG = ROOT / "assets/memes/catalog.yaml"
MAX_GAIN_DB = 12.0


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = yaml.safe_load(CATALOG.read_text())
    return {"folder": ROOT / data["carpeta"], "memes": {m["id"]: m for m in data["memes"]}}


def meme(meme_id: str) -> dict:
    memes = catalog()["memes"]
    if meme_id not in memes:
        raise KeyError(f"El meme «{meme_id}» no está en {CATALOG.relative_to(ROOT)}")
    return memes[meme_id]


def path_of(meme_id: str) -> Path:
    return catalog()["folder"] / meme(meme_id)["archivo"]


def gain_for(meme_id: str, target_mean_db: float) -> float:
    gain = target_mean_db - meme(meme_id)["volumen_medio_db"]
    return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain)), 1)


SHEET = ROOT / "assets/memes/catalogo.md"
THUMBS = ROOT / "assets/memes/thumbs"


def thumbnail(meme_id: str) -> Path:
    target = THUMBS / f"{meme_id}.jpg"
    if not target.exists():
        THUMBS.mkdir(parents=True, exist_ok=True)
        ffmpeg("-ss", f"{meme(meme_id)['duracion'] * 0.4:.2f}", "-i", path_of(meme_id),
               "-frames:v", 1, "-vf", "scale=200:-2", target)
    return target


def is_meme_slot(spec: dict) -> bool:
    if spec.get("title"):
        return True
    skipped = ("meme", "nametag", "broll", "freeze", "cover")
    return not any(key in spec for key in skipped)


def meme_slots(project) -> list:
    clips, cut_map = project.config["clips"], read_json(project.build / "cut_map.json")
    corrections = project.config.get("transcription", {}).get("corrections", [])
    words = words_of(read_json(project.dir / "transcript.json"), cut_map, corrections)
    rows = []
    for index, spec in enumerate(clips):
        if not is_meme_slot(spec):
            continue
        following = clips[index + 1] if index + 1 < len(clips) else {}
        span = cut_map["clips"][spec["id"]]
        said = spec["title"].replace("\n", " ") if spec.get("title") else spoken_in(words, span["start"], span["end"])
        rows.append((mmss(span["end"]), spec["id"], said, following.get("meme", "")))
    return rows


def selection_sheet(projects: list) -> str:
    out = ["# Memes — qué usar y cuándo", "",
           "En cada parte, escribe en la columna **¿Cuál?** el id del meme que quieres después de ese momento, "
           "o «—» para no poner ninguno. Si lo dejas en blanco, queda el actual.", ""]
    for project in projects:
        out += [f"## {project.config.get('title', project.slug)}", "",
                "| Reel | Después de | Qué se dice | Meme actual | ¿Cuál? |", "|---|---|---|---|---|"]
        for at, clip_id, said, current in meme_slots(project):
            out.append(f"| {at} | {clip_id} | {said.replace('|', '/')} | {current} | |")
        out.append("")
    out += ["## Catálogo", "", "| | id | Dura | Qué es | Audio | Para qué sirve |", "|---|---|---|---|---|---|"]
    for meme_id, entry in sorted(catalog()["memes"].items()):
        thumb = thumbnail(meme_id).relative_to(SHEET.parent)
        out.append(f"| ![]({thumb}) | `{meme_id}` | {entry['duracion']} s | {entry['que_es']} | {entry['audio']} | "
                   f"{entry['uso']} |")
    return "\n".join(out) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Catálogo de memes con los momentos de cada reel para elegir")
    parser.add_argument("projects", type=Path, nargs="+")
    parser.add_argument("--force", action="store_true", help="reescribe el catálogo aunque ya tenga anotaciones")
    args = parser.parse_args()
    if SHEET.exists() and not args.force:
        sys.exit(f"{SHEET} ya existe y puede tener tus anotaciones; usa --force para reescribirlo")
    SHEET.write_text(selection_sheet([load(p) for p in args.projects]))
    print(SHEET)


if __name__ == "__main__":
    main()
