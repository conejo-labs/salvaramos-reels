import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from captions import ass_color, ass_time, caption_word, display, paginate, word_states  # noqa: E402
from compose import resolve_point, resolve_span  # noqa: E402
from cut import merge_ranges, runs, voice_threshold  # noqa: E402
import numpy as np  # noqa: E402
from transcribe import corrected, normalize_text, words_of  # noqa: E402

PAGING = {"max_words": 3, "max_duration": 1.2, "break_gap": 0.3, "tail": 0.15}


def w(word, start, end):
    return {"word": word, "start": start, "end": end}


def test_page_holds_at_most_three_words():
    words = [w(str(i), i * 0.2, i * 0.2 + 0.15) for i in range(7)]
    assert [len(p["words"]) for p in paginate(words, PAGING)] == [3, 3, 1]


def test_page_breaks_on_silence_longer_than_gap():
    words = [w("a", 0.0, 0.2), w("b", 0.6, 0.8)]
    pages = paginate(words, PAGING)
    assert len(pages) == 2
    assert pages[0]["end"] == pytest.approx(0.35)


def test_page_breaks_when_duration_exceeded():
    words = [w("a", 0.0, 0.5), w("b", 0.5, 1.0), w("c", 1.0, 1.5)]
    assert [len(p["words"]) for p in paginate(words, PAGING)] == [2, 1]


def test_page_breaks_after_sentence_end_and_at_clip_boundary():
    assert len(paginate([w("Hola.", 0, 0.2), w("chao", 0.25, 0.4)], PAGING)) == 2
    assert len(paginate([w("a", 0, 0.2), w("b", 0.25, 0.4)], PAGING, boundaries=[0.22])) == 2
    assert len(paginate([w("a", 0, 0.2), w("b", 0.19, 0.4)], PAGING, boundaries=[0.22])) == 2


def test_page_breaks_where_whisper_starts_a_segment():
    words = [w("ramos", 0, 0.2), dict(w("Una", 0.25, 0.4), starts_segment=True)]
    assert len(paginate(words, PAGING)) == 2


def test_page_extends_until_next_when_gap_is_short():
    pages = paginate([w(str(i), i * 0.3, i * 0.3 + 0.2) for i in range(4)], PAGING)
    assert pages[0]["end"] == pages[1]["start"]


def test_word_states_cover_page_without_gaps():
    page = paginate([w("a", 0.1, 0.3), w("b", 0.35, 0.5), w("c", 0.55, 0.7)], PAGING)[0]
    states = word_states(page)
    assert states[0][0] == page["start"]
    assert all(states[i][1] == states[i + 1][0] for i in range(len(states) - 1))
    assert states[-1][1] == page["end"]


def test_ass_color_is_bgr():
    assert ass_color("#FFD400") == "&H0000D4FF"


def test_ass_time_format():
    assert ass_time(3723.456) == "1:02:03.46"


def test_captions_drop_trailing_punctuation_but_texts_keep_it():
    assert caption_word("cálculo.", True) == "CÁLCULO"
    assert caption_word("¿final?", False) == "¿final?"
    assert display("CÓDIGO:", True) == "CÓDIGO:"


def test_merge_ranges_joins_short_gaps_and_drops_short_keeps():
    assert merge_ranges([(0, 10), (12, 20), (40, 42), (60, 90)], min_gap=5, min_keep=5, total=80) == [(0, 20), (60, 80)]


def test_normalize_text_ignores_case_accents_and_punctuation():
    assert normalize_text("¿Fútbol?") == "futbol"


def test_words_of_places_each_clip_at_its_timeline_start_and_skips_missing_clips():
    transcript = {"clips": {"b": {"key": "k", "segments": [{"words": [w("chao", 0.5, 0.7)]}]},
                            "a": {"key": "k", "segments": [{"words": [w("hola", 0.1, 0.3), w("tú", 0.4, 0.5)]}]},
                            "gone": {"key": "k", "segments": [{"words": [w("x", 0, 1)]}]}}}
    cut_map = {"clips": {"a": {"start": 0.0}, "b": {"start": 10.0}}}
    words = words_of(transcript, cut_map)
    assert [x["word"] for x in words] == ["hola", "tú", "chao"]
    assert words[2]["start"] == 10.5
    assert [x["starts_segment"] for x in words] == [True, False, True]


CUT_MAP = {"duration": 30.0, "clips": {"intro": {"start": 5.0, "end": 12.0}}}
WORDS = [w("Hola", 1.0, 1.2), w("fútbol", 3.0, 3.4), w("Fútbol.", 8.0, 8.4)]


def test_resolve_point_by_clip_word_and_number():
    assert resolve_point(2.5, CUT_MAP, WORDS) == 2.5
    assert resolve_point({"clip": "intro", "offset": 1}, CUT_MAP, WORDS) == 6.0
    assert resolve_point({"word": "futbol", "occurrence": 2}, CUT_MAP, WORDS) == 8.0
    with pytest.raises(ValueError):
        resolve_point({"word": "punto"}, CUT_MAP, WORDS)


def test_resolve_span_defaults_to_clip_end_and_clamps_to_duration():
    assert resolve_span({"at": {"clip": "intro"}}, CUT_MAP, WORDS) == (5.0, 12.0)
    assert resolve_span({"at": 28.0, "duration": 5}, CUT_MAP, WORDS) == (28.0, 30.0)
    assert resolve_span({"at": 1.0, "until": {"clip": "intro"}}, CUT_MAP, WORDS) == (1.0, 12.0)


def test_page_does_not_spill_into_next_clip():
    pages = paginate([w("UdeC", 1.0, 1.4)], PAGING, boundaries=[0.0, 1.45])
    assert pages[0]["end"] == 1.45


def test_corrections_keep_timing_when_word_count_matches_and_respace_when_not():
    words = [w("una", 0.0, 0.2), w("entrega", 0.2, 0.6), w("última", 0.6, 1.0), w("hora", 1.0, 1.2)]
    fixed = corrected(words, "entrega última", "entrega a última")
    assert [x["word"] for x in fixed] == ["una", "entrega", "a", "última", "hora"]
    assert fixed[1]["start"] == 0.2 and fixed[3]["end"] == 1.0
    assert corrected(words, "hora", "hora.")[3] == w("hora.", 1.0, 1.2)


def test_corrections_apply_only_to_their_clip():
    transcript = {"clips": {"a": {"segments": [{"words": [w("puto", 0, 1)]}]},
                            "b": {"segments": [{"words": [w("puto", 0, 1)]}]}}}
    cut_map = {"clips": {"a": {"start": 0.0}, "b": {"start": 5.0}}}
    words = words_of(transcript, cut_map, [{"clip": "a", "find": "puto", "replace": "punto"}])
    assert [x["word"] for x in words] == ["punto", "puto"]


def test_runs_finds_each_stretch_above_threshold():
    assert [(int(a), int(b)) for a, b in runs(np.array([0, 1, 1, 0, 0, 1, 0, 1]) > 0)] == [(1, 3), (5, 6), (7, 8)]


def test_voice_threshold_follows_the_noise_floor_within_limits():
    settings = {"floor_percentile": 10, "above_floor_db": 10, "min_db": -52, "max_db": -36}
    assert voice_threshold(np.full(100, -60.0), settings) == -50.0
    assert voice_threshold(np.full(100, -20.0), settings) == -36.0
    assert voice_threshold(np.full(100, -75.0), settings) == -52.0


def test_raw_sources_resolve_inside_the_event_media_folder():
    from project import Project
    from util import MEDIA
    project = Project(dir=Path("/tmp/projects/reel-1"), config={"event": "jing-2026"}, style={})
    assert project.path("raw/IMG_1.MOV") == MEDIA / "eventos" / "jing-2026" / "raw" / "IMG_1.MOV"
    assert Project(dir=Path("/tmp/projects/solo"), config={}, style={}).event == "solo"


def test_sfx_catalog_is_consistent():
    from sfx import catalog, lead_in
    data = catalog()
    for sound_id, entry in data["sounds"].items():
        start, end = entry["recorte"]
        assert entry["categoria"] in data["categories"], sound_id
        assert 0 <= start < end, sound_id
        assert start <= entry["pico"] <= end, sound_id
        assert entry["duracion"] == pytest.approx(end - start, abs=0.02), sound_id
        assert entry["archivo"] == f"{sound_id}.wav", sound_id
        assert lead_in(entry) >= 0


def test_sfx_gain_matches_target_and_is_capped():
    from sfx import gain_for
    assert gain_for("golpe", -19.2) == 0.0
    assert gain_for("yeet", -30) == -12.0
