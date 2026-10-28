import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from pathlib import Path

from util import ROOT, ffmpeg, write_json

API = "https://api.giphy.com/v1/gifs"
LIBRARY = ROOT / "assets/memes/giphy"
PREFIX = "giphy:"


def api_key() -> str:
    if os.environ.get("GIPHY_API_KEY"):
        return os.environ["GIPHY_API_KEY"]
    env_file = ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            name, _, value = line.partition("=")
            if name.strip() == "GIPHY_API_KEY" and value.strip():
                return value.strip()
    sys.exit("Falta GIPHY_API_KEY: ponla en .env (GIPHY_API_KEY=...) o en el entorno")


def _get(url: str, params: dict) -> dict:
    query = urllib.parse.urlencode({"api_key": api_key(), **params})
    with urllib.request.urlopen(f"{url}?{query}", timeout=20) as response:
        return json.load(response)


def _summary(gif: dict) -> dict:
    original = gif["images"]["original"]
    return {"id": gif["id"], "title": gif.get("title", ""), "url": gif.get("url", ""),
            "username": gif.get("username", ""), "source": gif.get("source", ""),
            "mp4": original.get("mp4"), "width": int(original["width"]), "height": int(original["height"])}


def search(query: str, limit: int = 8, lang: str = "es") -> list:
    data = _get(f"{API}/search", {"q": query, "limit": limit, "rating": "pg-13", "lang": lang})
    return [_summary(g) for g in data["data"]]


def is_giphy(src: str) -> bool:
    return src.startswith(PREFIX)


def fetch(gif_id: str) -> Path:
    target = LIBRARY / f"{gif_id}.mp4"
    if target.exists():
        return target
    LIBRARY.mkdir(parents=True, exist_ok=True)
    gif = _summary(_get(f"{API}/{gif_id}", {})["data"])
    urllib.request.urlretrieve(gif["mp4"], target)
    write_json(target.with_suffix(".json"), gif)
    return target


def resolve(src: str) -> Path:
    return fetch(src[len(PREFIX):])


def search_sheet(query: str, results: list) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-")
    sheet = LIBRARY / f"_search_{slug}.png"
    paths = [fetch(r["id"]) for r in results]
    inputs = [x for p in paths for x in ("-i", p)]
    tiles = "".join(
        f"[{i}:v]trim=end_frame=1,scale=300:300:force_original_aspect_ratio=decrease,"
        f"pad=300:300:(ow-iw)/2:(oh-ih)/2:black,drawtext=text='{i}':x=8:y=8:fontsize=36:fontcolor=yellow:"
        f"box=1:boxcolor=black@0.6[t{i}];"
        for i in range(len(paths)))
    layout = "|".join(f"{(i % 4) * 300}_{(i // 4) * 300}" for i in range(len(paths)))
    ffmpeg(*inputs, "-filter_complex", tiles + "".join(f"[t{i}]" for i in range(len(paths))) +
           f"xstack=inputs={len(paths)}:layout={layout}:fill=black", "-frames:v", 1, sheet)
    return sheet


def main() -> None:
    parser = argparse.ArgumentParser(description="Busca memes en Giphy y los deja en assets/memes/giphy")
    parser.add_argument("query")
    parser.add_argument("--limit", type=int, default=8)
    parser.add_argument("--lang", default="es")
    args = parser.parse_args()
    results = search(args.query, args.limit, args.lang)
    for i, r in enumerate(results):
        print(f"[{i}] giphy:{r['id']}  {r['width']}x{r['height']}  {r['title']}  {r['url']}")
    if len(results) > 1:
        print(search_sheet(args.query, results))


if __name__ == "__main__":
    main()
