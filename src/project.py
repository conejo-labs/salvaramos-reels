from dataclasses import dataclass
from pathlib import Path

import yaml

from util import MEDIA, ROOT


def deep_merge(base: dict, override: dict) -> dict:
    merged = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


@dataclass
class Project:
    dir: Path
    config: dict
    style: dict

    @property
    def slug(self) -> str:
        return self.dir.name

    @property
    def build(self) -> Path:
        path = self.dir / "build"
        path.mkdir(exist_ok=True)
        return path

    @property
    def fonts_dir(self) -> Path:
        return ROOT / self.style["fonts_dir"]

    @property
    def event(self) -> str:
        return self.config.get("event", self.slug)

    def path(self, relative: str) -> Path:
        if relative.startswith("raw/"):
            return MEDIA / "eventos" / self.event / relative
        return (self.dir / relative).resolve()

    def font_file(self, name: str) -> Path:
        return self.fonts_dir / name


def trim_ranges(trim) -> list:
    if not trim:
        return []
    return [tuple(trim)] if isinstance(trim[0], (int, float)) else [tuple(r) for r in trim]


def load(project_dir: Path, style_path: Path = ROOT / "presets/style.yaml") -> Project:
    project_dir = project_dir.resolve()
    config = yaml.safe_load((project_dir / "config.yaml").read_text())
    style = yaml.safe_load(style_path.read_text())
    style = deep_merge(style, config.get("style", {}))
    return Project(dir=project_dir, config=config, style=style)
