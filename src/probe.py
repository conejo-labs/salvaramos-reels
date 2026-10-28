import json
from fractions import Fraction
from pathlib import Path

from util import run

HDR_TRANSFERS = {"arib-std-b67", "smpte2084"}


def _rotation(stream: dict) -> int:
    for side_data in stream.get("side_data_list", []):
        if "rotation" in side_data:
            return int(side_data["rotation"])
    return int(stream.get("tags", {}).get("rotate", 0))


def probe(path: Path) -> dict:
    result = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_format", "-show_streams", path],
                 capture_output=True, text=True)
    data = json.loads(result.stdout)
    video = next(s for s in data["streams"] if s["codec_type"] == "video")
    has_audio = any(s["codec_type"] == "audio" for s in data["streams"])
    rotation = _rotation(video)
    width, height = video["width"], video["height"]
    if abs(rotation) == 90:
        width, height = height, width
    avg_fps, nominal_fps = Fraction(video["avg_frame_rate"]), Fraction(video["r_frame_rate"])
    return {
        "duration": float(data["format"]["duration"]),
        "width": width,
        "height": height,
        "rotation": rotation,
        "fps": float(avg_fps) if avg_fps else float(nominal_fps),
        "vfr": avg_fps != nominal_fps,
        "hdr": video.get("color_transfer") in HDR_TRANSFERS,
        "has_audio": has_audio,
        "codec": video["codec_name"],
    }
