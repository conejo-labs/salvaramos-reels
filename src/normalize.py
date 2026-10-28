from pathlib import Path

from probe import probe
from project import Project
from util import code_signature, digest, ffmpeg, file_signature, is_fresh, seal

TONEMAP_TO_SDR = ("zscale=t=linear:npl=100,format=gbrpf32le,zscale=p=bt709,"
                  "tonemap=hable:desat=0,zscale=t=bt709:m=bt709:r=tv")


def fill_frame(width: int, height: int) -> list:
    return [f"scale={width}:{height}:force_original_aspect_ratio=increase:flags=lanczos", f"crop={width}:{height}"]


def fit_inside(width: int, height: int) -> list:
    return [f"scale={width}:{height}:force_original_aspect_ratio=decrease:force_divisible_by=2:flags=lanczos"]


def video_filter(info: dict, framing: list, fps: int) -> str:
    chain = [TONEMAP_TO_SDR] if info["hdr"] else []
    chain += [*framing, "setsar=1", f"fps={fps}", "tpad=stop=-1:stop_mode=clone", "format=yuv420p"]
    return ",".join(chain)


def normalize(project: Project, src: Path, trim: list | None = None, gain_db: float = 0.0,
              box: tuple[int, int] | None = None, loop: bool = False) -> Path:
    canvas, settings = project.style["canvas"], project.style["normalize"]
    info = probe(src)
    start, end = trim if trim else (0.0, info["duration"])
    if not loop:
        end = min(end, info["duration"])
    frames = round((end - start) * canvas["fps"])
    framing = fit_inside(*box) if box else fill_frame(canvas["width"], canvas["height"])
    key = digest(file_signature(src), start, end, gain_db, framing, loop, canvas, settings, code_signature(__file__))
    output = project.build / "norm" / f"{src.stem}_{key}.mkv"
    if is_fresh(output, key):
        return output
    output.parent.mkdir(exist_ok=True)

    looping = ["-stream_loop", "-1"] if loop else []
    audio_input = [] if info["has_audio"] else ["-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo"]
    audio_map = "0:a:0" if info["has_audio"] else "1:a:0"
    ffmpeg(
        *looping, "-ss", f"{start:.3f}", "-t", f"{end - start:.3f}", "-i", src, *audio_input,
        "-map", "0:v:0", "-map", audio_map,
        "-vf", video_filter(info, framing, canvas["fps"]),
        "-af", f"aresample=48000,aformat=sample_fmts=s16:channel_layouts=stereo,volume={gain_db}dB,apad",
        "-frames:v", frames, "-t", f"{frames / canvas['fps']:.6f}",
        "-c:v", "libx264", "-crf", settings["crf"], "-preset", settings["preset"],
        "-c:a", "pcm_s16le", output,
    )
    seal(output, key)
    return output
