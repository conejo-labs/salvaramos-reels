from pathlib import Path

import numpy as np

from project import Project
from transcribe import pcm16k
from util import code_signature, digest, ffmpeg, file_signature, is_fresh, read_json, seal, write_json

SAMPLE_RATE = 48000
HOP_SECONDS = 0.01


def merge_ranges(ranges: list, min_gap: int, min_keep: int, total: int) -> list:
    merged = []
    for start, end in sorted(ranges):
        start, end = max(0, start), min(total, end)
        if merged and start - merged[-1][1] < min_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(s, e) for s, e in merged if e - s >= min_keep]


def level_db(clip_path: Path) -> np.ndarray:
    audio = pcm16k(clip_path)
    hop = int(16000 * HOP_SECONDS)
    count = len(audio) // hop
    rms = np.sqrt(np.mean(audio[:count * hop].reshape(count, hop) ** 2, axis=1) + 1e-12)
    return 20 * np.log10(rms)


def runs(flags: np.ndarray) -> list:
    edges = np.diff(np.concatenate([[0], flags.astype(np.int8), [0]]))
    return list(zip(np.flatnonzero(edges == 1), np.flatnonzero(edges == -1)))


def voice_threshold(levels: np.ndarray, settings: dict) -> float:
    floor = np.percentile(levels, settings["floor_percentile"])
    return float(np.clip(floor + settings["above_floor_db"], settings["min_db"], settings["max_db"]))


def voiced_ranges(project: Project, clip_path: Path, total_frames: int) -> list:
    settings, fps = project.style["cut"], project.style["canvas"]["fps"]
    levels = level_db(clip_path)
    pad = settings["pad"]
    ranges = [(round((a * HOP_SECONDS - pad) * fps), round((b * HOP_SECONDS + pad) * fps))
              for a, b in runs(levels > voice_threshold(levels, settings))]
    return merge_ranges(ranges, round(settings["min_gap"] * fps), round(settings["min_keep"] * fps), total_frames)


def segment_motion(clip_index: int, range_index: int, jump_cuts: bool) -> str | None:
    if range_index == 0 and clip_index > 0:
        return "entry"
    if jump_cuts and range_index % 2 == 1:
        return "punch"
    return None


def motion_filter(motion: str | None, transitions: dict, canvas: dict) -> str:
    width, height, fps = canvas["width"], canvas["height"], canvas["fps"]
    if motion == "punch":
        zoom = transitions["punch_in"]
        return f",scale={round(width * zoom / 2) * 2}:{round(height * zoom / 2) * 2},crop={width}:{height}"
    if motion == "entry":
        zoom, frames = transitions["entry_zoom"], transitions["entry_frames"]
        ease_out = f"1+{zoom - 1:.4f}*pow(max(0,1-on/{frames}),2)"
        return (f",zoompan=z='{ease_out}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
                f":d=1:s={width}x{height}:fps={fps}")
    return ""


def segment_filter(source: str, n: int, start: int, end: int, fps: int, fade: float, motion: str = "") -> str:
    samples_per_frame = SAMPLE_RATE // fps
    duration = (end - start) / fps
    return (
        f"[v{source}]trim=start_frame={start}:end_frame={end},setpts=PTS-STARTPTS{motion},setsar=1[sv{n}];"
        f"[a{source}]atrim=start_sample={start * samples_per_frame}:end_sample={end * samples_per_frame},"
        f"asetpts=PTS-STARTPTS,afade=t=in:d={fade},afade=t=out:st={max(0.0, duration - fade):.4f}:d={fade}[sa{n}]"
    )


def cut(project: Project, clips: list) -> tuple[Path, dict]:
    settings, canvas = project.style["cut"], project.style["canvas"]
    transitions, fps = project.style["transitions"], canvas["fps"]
    key = digest([(c["id"], file_signature(c["path"]), c["keep"], c["silence"], c["captions"], c["kind"])
                  for c in clips],
                 settings, transitions, canvas, code_signature(__file__))
    output, map_path = project.build / "cut.mkv", project.build / "cut_map.json"
    if is_fresh(output, key) and map_path.exists():
        return output, read_json(map_path)

    plan = []
    for index, clip in enumerate(clips):
        whole = [(0, clip["frames"])]
        if clip["keep"]:
            ranges = [(a, min(b, clip["frames"])) for a, b in clip["keep"]]
        elif clip["silence"] and settings["silence"]:
            ranges = voiced_ranges(project, clip["path"], clip["frames"])
        else:
            ranges = whole
        plan.append((index, clip, ranges or whole))

    inputs, graph, labels, segments, clip_spans = [], [], [], [], {}
    cursor = 0
    for index, clip, ranges in plan:
        inputs += ["-i", clip["path"]]
        count = len(ranges)
        graph.append(f"[{index}:v]split={count}" + "".join(f"[v{index}_{n}]" for n in range(count)))
        graph.append(f"[{index}:a]asplit={count}" + "".join(f"[a{index}_{n}]" for n in range(count)))
        for k, (start, end) in enumerate(ranges):
            n = len(segments)
            motion = segment_motion(index, k, jump_cuts=count > 1)
            graph.append(segment_filter(f"{index}_{k}", n, start, end, fps, settings["fade"],
                                        motion_filter(motion, transitions, canvas)))
            labels.append(f"[sv{n}][sa{n}]")
            segments.append({"clip": clip["id"], "src_start": start / fps, "src_end": end / fps,
                             "start": cursor / fps, "end": (cursor + end - start) / fps, "motion": motion})
            cursor += end - start
        clip_spans[clip["id"]] = {"start": segments[-count]["start"], "end": cursor / fps,
                                  "captions": clip["captions"], "kind": clip["kind"]}
    graph.append("".join(labels) + f"concat=n={len(segments)}:v=1:a=1[v][a]")

    ffmpeg(*inputs, "-filter_complex", ";".join(graph), "-map", "[v]", "-map", "[a]",
           "-c:v", "libx264", "-crf", project.style["normalize"]["crf"], "-preset", project.style["normalize"]["preset"],
           "-c:a", "pcm_s16le", output)
    cut_map = {"key": key, "fps": fps, "duration": cursor / fps, "segments": segments, "clips": clip_spans}
    write_json(map_path, cut_map)
    seal(output, key)
    return output, cut_map
