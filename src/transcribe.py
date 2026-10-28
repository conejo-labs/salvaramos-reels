import re
import subprocess
import unicodedata
from pathlib import Path

import numpy as np

from project import Project
from util import digest, read_json, write_json


def normalize_text(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^\w ]", "", stripped).strip()


def pcm16k(path: Path, start: float = 0.0, duration: float | None = None) -> np.ndarray:
    window = ["-ss", f"{start:.3f}"] + (["-t", f"{duration:.3f}"] if duration else [])
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", *window, "-i", str(path), "-vn", "-ac", "1",
                          "-ar", "16000", "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def whisper_device() -> tuple[str, str]:
    import ctranslate2
    return ("cuda", "float16") if ctranslate2.get_cuda_device_count() > 0 else ("cpu", "int8")


class Whisper:
    def __init__(self, project: Project):
        self.settings = project.style["transcription"]
        self.vocabulary = self.settings["vocabulary"] + project.config.get("transcription", {}).get("vocabulary", [])
        self.hallucinations = {normalize_text(h) for h in self.settings["hallucinations"]}
        self.model = None

    def segments(self, audio: np.ndarray) -> list:
        if self.model is None:
            from faster_whisper import WhisperModel
            device, compute_type = whisper_device()
            self.model = WhisperModel(self.settings["model"], device=device, compute_type=compute_type)
        segments, _ = self.model.transcribe(audio, language=self.settings["language"],
                                            initial_prompt=", ".join(self.vocabulary), word_timestamps=True,
                                            vad_filter=True)
        kept = []
        for segment in segments:
            if segment.no_speech_prob > self.settings["no_speech_threshold"]:
                continue
            if normalize_text(segment.text) in self.hallucinations:
                continue
            words = [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)}
                     for w in segment.words if w.word.strip()]
            if words:
                kept.append({"words": words})
        return kept


def clip_key(spec: dict, cut_map: dict) -> str:
    used = [(s["src_start"], s["src_end"]) for s in cut_map["segments"] if s["clip"] == spec["id"]]
    return digest(spec.get("src"), spec.get("trim"), used)


def transcribe(project: Project, cut_path: Path, cut_map: dict, retranscribe: bool = False) -> dict:
    path = project.dir / "transcript.json"
    transcript = read_json(path) if path.exists() else {}
    clips, previous = transcript.get("clips", {}), transcript.get("previous", {})
    whisper, changed = Whisper(project), []
    captioned = {spec["id"]: spec for spec in project.config["clips"] if cut_map["clips"][spec["id"]]["captions"]}
    for clip_id, spec in captioned.items():
        key, entry = clip_key(spec, cut_map), clips.get(clip_id)
        if entry and entry["key"] == key and not retranscribe:
            continue
        if entry:
            previous[clip_id] = entry
        span = cut_map["clips"][clip_id]
        audio = pcm16k(cut_path, span["start"], span["end"] - span["start"])
        clips[clip_id] = {"key": key, "segments": whisper.segments(audio)}
        changed.append(clip_id)
    for clip_id in [c for c in clips if c not in captioned]:
        previous[clip_id] = clips.pop(clip_id)
        changed.append(clip_id)
    transcript = {"model": project.style["transcription"]["model"], "clips": clips}
    if previous:
        transcript["previous"] = previous
    if changed or not path.exists():
        write_json(path, transcript)
        print(f"  transcribí o retiré: {', '.join(changed)}", flush=True)
    return transcript


def respaced(span: list, replacement: list) -> list:
    if len(span) == len(replacement):
        return [dict(w, word=new) for w, new in zip(span, replacement)]
    start, end = span[0]["start"], span[-1]["end"]
    total, cursor, words = sum(len(r) for r in replacement), start, []
    for new in replacement:
        length = (end - start) * len(new) / total
        words.append({"word": new, "start": round(cursor, 3), "end": round(cursor + length, 3)})
        cursor += length
    return words


def corrected(words: list, find: str, replace: str) -> list:
    old, new = find.split(" "), replace.split(" ")
    result, i = [], 0
    while i < len(words):
        if [w["word"] for w in words[i:i + len(old)]] == old:
            result += respaced(words[i:i + len(old)], new)
            i += len(old)
        else:
            result.append(words[i])
            i += 1
    return result


def words_of(transcript: dict, cut_map: dict, corrections: list = ()) -> list:
    words = []
    for clip_id, entry in transcript["clips"].items():
        if clip_id not in cut_map["clips"]:
            continue
        offset = cut_map["clips"][clip_id]["start"]
        rules = [c for c in corrections if c.get("clip", clip_id) == clip_id]
        for segment in entry["segments"]:
            fixed = segment["words"]
            for rule in rules:
                fixed = corrected(fixed, rule["find"], rule["replace"])
            for i, word in enumerate(fixed):
                words.append({"word": word["word"], "start": round(word["start"] + offset, 3),
                              "end": round(word["end"] + offset, 3), "starts_segment": i == 0})
    return sorted(words, key=lambda w: w["start"])
