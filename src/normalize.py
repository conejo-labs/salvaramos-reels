import json
import math
import re
import subprocess
from pathlib import Path

from probe import probe
from project import Project
from util import code_signature, digest, ffmpeg, file_signature, is_fresh, seal

MAX_LEVEL_GAIN_DB = 15.0
TONEMAP_TO_SDR = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                  "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")


def fill_frame(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos,crop={width}:{height}"


def fit_inside(width: int, height: int) -> str:
    return f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"


def over_blurred_copy(width: int, height: int, blur: dict) -> str:
    return (f"split[bg][fg];[bg]{fill_frame(width, height)},boxblur={blur['radius']}:2,"
            f"eq=brightness={blur['brightness']}[bgb];[fg]{fit_inside(width, height)}[fgs];"
            "[bgb][fgs]overlay=(W-w)/2:(H-h)/2")


def framing_filter(framing: str, canvas: dict, box: tuple | None, blur: dict) -> str:
    if box:
        return fit_inside(*box)
    if framing == "blur":
        return over_blurred_copy(canvas["width"], canvas["height"], blur)
    return fill_frame(canvas["width"], canvas["height"])


def video_filter(info: dict, framing: str, look: str | None, fps: int) -> str:
    chain = [TONEMAP_TO_SDR] if info["hdr"] else []
    chain += [framing, "setsar=1", f"fps={fps}", "tpad=stop=-1:stop_mode=clone"]
    if look:
        chain.append(look)
    chain.append("format=yuv420p")
    return ",".join(chain)


def integrated_loudness(src: Path, start: float, seconds: float) -> float | None:
    result = subprocess.run(["ffmpeg", "-hide_banner", "-nostdin", "-ss", f"{start:.3f}", "-t", f"{seconds:.3f}",
                             "-i", str(src), "-vn", "-af", "loudnorm=print_format=json", "-f", "null", "-"],
                            capture_output=True, text=True, check=True)
    measured = json.loads(re.search(r"\{[^{}]*\}\s*$", result.stderr).group(0))["input_i"]
    return None if measured == "-inf" else float(measured)


def level_gain(src: Path, ranges: list, target_lufs: float) -> float:
    energy = duration = 0.0
    for start, end in ranges:
        measured = integrated_loudness(src, start, end - start)
        if measured is not None:
            energy += (end - start) * 10 ** (measured / 10)
            duration += end - start
    if not duration:
        return 0.0
    measured = 10 * math.log10(energy / duration)
    return max(-MAX_LEVEL_GAIN_DB, min(MAX_LEVEL_GAIN_DB, target_lufs - measured))


def normalize(project: Project, src: Path, trim: list | None = None, gain_db: float = 0.0,
              box: tuple[int, int] | None = None, loop: bool = False, framing: str = "fill",
              look: str | None = None, freeze: bool = False, audio_src: Path | None = None, silent: bool = False,
              level_to: float | None = None, level_ranges: list | None = None) -> Path:
    canvas, settings = project.style["canvas"], project.style["normalize"]
    info = probe(src)
    start, end = trim if trim else (0.0, info["duration"])
    if not (loop or freeze):
        end = min(end, info["duration"])
    frames = round((end - start) * canvas["fps"])
    read_seconds = 1 / canvas["fps"] if freeze else end - start
    look_filter = project.style["looks"][look] if look else None
    graph = framing_filter(framing, canvas, box, project.style["memes"]["blur"])
    key = digest(file_signature(src), start, end, gain_db, level_to, level_ranges, graph, look_filter, loop, freeze,
                 file_signature(audio_src) if audio_src else None, silent, canvas, settings, code_signature(__file__))
    output = project.build / "norm" / f"{src.stem}_{key}.mkv"
    if is_fresh(output, key):
        return output
    output.parent.mkdir(exist_ok=True)
    if level_to is not None:
        gain_db += level_gain(src, level_ranges or [(start, end)], level_to)

    looping = ["-stream_loop", "-1"] if loop else []
    if audio_src:
        audio_input, audio_map = ["-i", audio_src], "1:a:0"
    elif info["has_audio"] and not silent:
        audio_input, audio_map = [], "0:a:0"
    else:
        audio_input, audio_map = ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"], "1:a:0"
    ffmpeg(
        *looping, "-ss", f"{start:.3f}", "-t", f"{read_seconds:.3f}", "-i", src, *audio_input,
        "-map", "0:v:0", "-map", audio_map,
        "-vf", video_filter(info, graph, look_filter, canvas["fps"]),
        "-af", f"aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,volume={gain_db}dB,apad",
        "-frames:v", frames, "-t", f"{frames / canvas['fps']:.6f}",
        "-c:v", "libx264", "-crf", settings["crf"], "-preset", settings["preset"],
        "-c:a", "pcm_s16le", output,
    )
    seal(output, key)
    return output
