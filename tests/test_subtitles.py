"""字幕パースのテスト。ネットワークもTTSも不要な純粋ロジック部分。"""

from __future__ import annotations

import json

import pytest

from subdub.subtitles import parse_json3, parse_srt_vtt, ts_to_sec

SRT = """1
00:00:01,000 --> 00:00:03,500
最初の行

2
00:00:04,000 --> 00:00:06,000
二番目の行
折り返した続き
"""

VTT = """WEBVTT

NOTE これは無視される

00:00.000 --> 00:02.000
<v Speaker>タグ付きの行</v>

00:02.000 --> 00:04.000
&amp; の実体参照
"""


def test_ts_formats():
    assert ts_to_sec("00:00:01,500") == pytest.approx(1.5)
    assert ts_to_sec("01:02:03.250") == pytest.approx(3723.25)
    assert ts_to_sec("02:30.000") == pytest.approx(150.0)
    assert ts_to_sec("12.5") == pytest.approx(12.5)


def test_ts_invalid():
    with pytest.raises(ValueError):
        ts_to_sec("1:2:3:4")


def test_srt_basic():
    cues = parse_srt_vtt(SRT)
    assert len(cues) == 2
    assert cues[0].start == pytest.approx(1.0)
    assert cues[0].end == pytest.approx(3.5)
    assert cues[0].text == "最初の行"
    # 折り返しは1キューに連結される
    assert cues[1].text == "二番目の行 折り返した続き"


def test_srt_duration():
    cues = parse_srt_vtt(SRT)
    assert cues[0].dur == pytest.approx(2.5)


def test_vtt_strips_tags_and_entities():
    cues = parse_srt_vtt(VTT)
    assert len(cues) == 2
    assert cues[0].text == "タグ付きの行"
    assert cues[1].text == "& の実体参照"


def test_vtt_drops_note_block():
    assert all("無視される" not in c.text for c in parse_srt_vtt(VTT))


def test_empty_input():
    assert parse_srt_vtt("") == []


def test_json3():
    raw = json.dumps({"events": [
        {"tStartMs": 1000, "dDurationMs": 2000, "segs": [{"utf8": "あ"},
                                                         {"utf8": "い"}]},
        {"tStartMs": 4000, "dDurationMs": 1000, "segs": [{"utf8": "\n"}]},
        {"tStartMs": 5000, "dDurationMs": 1000},
    ]})
    cues = parse_json3(raw)
    assert len(cues) == 1          # 空白のみ・segs無しは落ちる
    assert cues[0].text == "あい"
    assert cues[0].start == pytest.approx(1.0)
    assert cues[0].end == pytest.approx(3.0)
