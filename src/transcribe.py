import re
import shutil
import subprocess
import unicodedata
from datetime import datetime
from pathlib import Path

import numpy as np

from project import Project
from util import is_fresh, read_json, seal, write_json


class StaleTranscript(Exception):
    pass


def normalize_text(text: str) -> str:
    stripped = unicodedata.normalize("NFKD", text.lower())
    stripped = "".join(c for c in stripped if not unicodedata.combining(c))
    return re.sub(r"[^\w ]", "", stripped).strip()


def pcm16k(path: Path) -> np.ndarray:
    raw = subprocess.run(["ffmpeg", "-v", "error", "-nostdin", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000",
                          "-f", "f32le", "-"], capture_output=True, check=True).stdout
    return np.frombuffer(raw, dtype=np.float32)


def whisper_device() -> tuple[str, str]:
    import ctranslate2
    return ("cuda", "float16") if ctranslate2.get_cuda_device_count() > 0 else ("cpu", "int8")


def muted_spans(cut_map: dict) -> list:
    return [(c["start"], c["end"]) for c in cut_map["clips"].values() if not c["captions"]]


def keep_word(word: dict, muted: list) -> bool:
    middle = (word["start"] + word["end"]) / 2
    return not any(start <= middle < end for start, end in muted)


def run_whisper(project: Project, audio_source: Path, cut_map: dict) -> dict:
    from faster_whisper import WhisperModel

    settings = project.style["transcription"]
    vocabulary = settings["vocabulary"] + project.config.get("transcription", {}).get("vocabulary", [])
    hallucinations = {normalize_text(h) for h in settings["hallucinations"]}
    device, compute_type = whisper_device()
    model = WhisperModel(settings["model"], device=device, compute_type=compute_type)
    segments, _ = model.transcribe(pcm16k(audio_source), language=settings["language"],
                                   initial_prompt=", ".join(vocabulary), word_timestamps=True, vad_filter=True)
    muted = muted_spans(cut_map)
    kept = []
    for segment in segments:
        if segment.no_speech_prob > settings["no_speech_threshold"]:
            continue
        if normalize_text(segment.text) in hallucinations:
            continue
        words = [{"word": w.word.strip(), "start": round(w.start, 3), "end": round(w.end, 3)} for w in segment.words]
        words = [w for w in words if w["word"] and keep_word(w, muted)]
        if words:
            kept.append({"words": words})
    return {"cut_key": cut_map["key"], "model": settings["model"], "device": device, "segments": kept}


def transcribe(project: Project, audio_source: Path, cut_map: dict, retranscribe: bool = False) -> dict:
    manual = project.dir / "transcript.json"
    if manual.exists() and not retranscribe:
        transcript = read_json(manual)
        if transcript.get("cut_key") == cut_map["key"]:
            return transcript
        auto = project.build / "transcript.auto.json"
        if not is_fresh(auto, cut_map["key"]):
            write_json(auto, run_whisper(project, audio_source, cut_map))
            seal(auto, cut_map["key"])
        raise StaleTranscript(
            f"{manual} se transcribió sobre otro corte. La versión nueva quedó en {auto}. "
            "Pasa tus correcciones a mano o usa --retranscribe (respalda la actual antes de reemplazarla).")
    if manual.exists():
        backup = manual.with_name(f"transcript.{datetime.now():%Y%m%d-%H%M%S}.bak.json")
        shutil.copy2(manual, backup)
    transcript = run_whisper(project, audio_source, cut_map)
    write_json(manual, transcript)
    return transcript


def words_of(transcript: dict) -> list:
    return [w for segment in transcript["segments"] for w in segment["words"]]
