import os
from functools import lru_cache
from html import escape
from pathlib import Path

import yaml

from util import ROOT

CATALOG = ROOT / "assets/sfx/catalog.yaml"
SHEET = ROOT / "assets/sfx/catalogo.html"
MAX_GAIN_DB = 12.0


@lru_cache(maxsize=1)
def catalog() -> dict:
    data = yaml.safe_load(CATALOG.read_text())
    return {"folder": ROOT / data["carpeta"], "categories": data["categorias"],
            "sounds": {s["id"]: s for s in data["sonidos"]}}


def sound(sound_id: str) -> dict:
    sounds = catalog()["sounds"]
    if sound_id not in sounds:
        raise KeyError(f"El sonido «{sound_id}» no está en {CATALOG.relative_to(ROOT)}")
    return sounds[sound_id]


def path_of(sound_id: str) -> Path:
    return catalog()["folder"] / sound(sound_id)["archivo"]


def gain_for(sound_id: str, target_mean_db: float) -> float:
    gain = target_mean_db - sound(sound_id)["volumen_medio_db"]
    return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain)), 1)


def lead_in(entry: dict) -> float:
    return round(entry["pico"] - entry["recorte"][0], 3)


def listening_sheet() -> str:
    folder = Path(os.path.relpath(catalog()["folder"].resolve(), SHEET.parent)).as_posix()
    out = ["<!doctype html><meta charset='utf-8'><title>Efectos de sonido</title>",
           "<style>body{font-family:system-ui;margin:2rem;max-width:72rem}td,th{padding:.3rem .6rem;"
           "text-align:left;vertical-align:middle}tr:nth-child(even){background:#f3f0ea}audio{height:2rem}</style>",
           "<h1>Efectos de sonido</h1>",
           "<p>Cada reproductor toca solo el <b>recorte</b>. El <b>pico</b> es el punto que cae en el evento.</p>"]
    for category, meaning in catalog()["categories"].items():
        out += [f"<h2>{escape(category)}</h2><p>{escape(meaning)}</p>",
                "<table><tr><th>id</th><th>Escuchar</th><th>Dura</th><th>Pico</th><th>Qué es</th><th>Uso</th></tr>"]
        for sound_id, entry in catalog()["sounds"].items():
            if entry["categoria"] != category:
                continue
            start, end = entry["recorte"]
            src = f"{folder}/{entry['archivo']}#t={start},{end}"
            out.append(f"<tr><td><code>{escape(sound_id)}</code></td>"
                       f"<td><audio controls preload='none' src='{escape(src)}'></audio></td>"
                       f"<td>{entry['duracion']} s</td><td>+{lead_in(entry)} s</td>"
                       f"<td>{escape(entry['que_es'])}</td><td>{escape(entry['uso'])}</td></tr>")
        out.append("</table>")
    return "\n".join(out) + "\n"


def main() -> None:
    SHEET.write_text(listening_sheet())
    print(SHEET)


if __name__ == "__main__":
    main()
