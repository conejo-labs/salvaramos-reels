import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEDIA = ROOT / "media"


def run(cmd, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(c) for c in cmd], check=True, **kwargs)


def ffmpeg(*args) -> None:
    run(["ffmpeg", "-hide_banner", "-nostdin", "-v", "error", "-y", *args])


def digest(*parts) -> str:
    h = hashlib.sha256()
    for part in parts:
        h.update(json.dumps(part, sort_keys=True, default=str).encode())
    return h.hexdigest()[:16]


def file_signature(path: Path) -> list:
    stat = path.stat()
    return [str(path.resolve()), stat.st_size, stat.st_mtime_ns]


def code_signature(module_file: str) -> str:
    return hashlib.sha256(Path(module_file).read_bytes()).hexdigest()[:16]


def _stamp(output: Path) -> Path:
    return output.with_name(output.name + ".key")


def is_fresh(output: Path, key: str) -> bool:
    stamp = _stamp(output)
    return output.exists() and stamp.exists() and stamp.read_text() == key


def seal(output: Path, key: str) -> None:
    _stamp(output).write_text(key)


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def read_json(path: Path):
    return json.loads(path.read_text())
