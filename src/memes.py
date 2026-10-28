from functools import lru_cache
from pathlib import Path

import yaml

from util import ROOT

CATALOG = ROOT / "assets/memes/catalog.yaml"


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


MAX_GAIN_DB = 12.0


def gain_for(meme_id: str, target_mean_db: float) -> float:
    gain = target_mean_db - meme(meme_id)["volumen_medio_db"]
    return round(max(-MAX_GAIN_DB, min(MAX_GAIN_DB, gain)), 1)
