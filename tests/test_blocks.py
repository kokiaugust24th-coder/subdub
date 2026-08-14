"""ブロック連結と発音辞書のテスト。"""

from __future__ import annotations

import json

import pytest

from subdub.blocks import build
from subdub.subtitles import Cue
from subdub.text import Normalizer


def c(start: float, end: float, text: str) -> Cue:
    return Cue(start, end, text)


def test_merges_continuing_sentence():
    """文が終わっていない連続キューは1ブロックにまとまる。"""
    cues = [c(0.0, 1.0, "これは"), c(1.0, 2.0, "続く文です。")]
    blocks = build(cues, merge_gap=0.35)
    assert len(blocks) == 1
    assert blocks[0].text == "これは 続く文です。"
    assert blocks[0].start == 0.0


def test_splits_on_sentence_end():
    cues = [c(0.0, 1.0, "終わりです。"), c(1.0, 2.0, "次の文です。")]
    assert len(build(cues, merge_gap=0.35)) == 2


def test_splits_on_large_gap():
    """間が空いていれば文が続いていても切る。"""
    cues = [c(0.0, 1.0, "前半"), c(5.0, 6.0, "後半")]
    assert len(build(cues, merge_gap=0.35)) == 2


def test_respects_max_block():
    cues = [c(0.0, 10.0, "長い"), c(10.0, 20.0, "続き")]
    assert len(build(cues, merge_gap=0.35, max_block=12.0)) == 2


def test_budget_is_until_next_start():
    """枠は字幕の表示終了ではなく «次の発話開始» まで。間も使える。"""
    cues = [c(0.0, 1.0, "一つ目。"), c(3.0, 4.0, "二つ目。")]
    blocks = build(cues)
    assert blocks[0].budget == pytest.approx(3.0)


def test_last_block_budget_is_unbounded():
    blocks = build([c(0.0, 1.0, "最後。")])
    assert blocks[0].budget == float("inf")


def test_skips_empty_cues():
    assert len(build([c(0.0, 1.0, "  "), c(1.0, 2.0, "実体。")])) == 1


# --- Normalizer ---------------------------------------------------------

def test_normalizer_without_dict_is_identity_ish():
    assert Normalizer().apply("  余白  を   潰す ") == "余白 を 潰す"


def test_normalizer_applies_regex_then_literal(tmp_path):
    d = tmp_path / "d.json"
    d.write_text(json.dumps({
        "regex": [[r"\[[^\]]*\]", ""]],
        "literal": {"dx": "ディーエックス"},
    }, ensure_ascii=False), encoding="utf-8")
    n = Normalizer(d)
    assert n.apply("[音楽] ここで dx が出る") == "ここで ディーエックス が出る"


def test_normalizer_longest_key_wins(tmp_path):
    d = tmp_path / "d.json"
    d.write_text(json.dumps({
        "literal": {"微分": "びぶん", "微分積分": "びぶんせきぶん"},
    }, ensure_ascii=False), encoding="utf-8")
    assert Normalizer(d).apply("微分積分") == "びぶんせきぶん"


def test_normalizer_missing_file():
    with pytest.raises(FileNotFoundError):
        Normalizer("does_not_exist.json")


def test_normalizer_bad_json(tmp_path):
    d = tmp_path / "bad.json"
    d.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ValueError):
        Normalizer(d)


def test_normalizer_bad_regex_entry(tmp_path):
    d = tmp_path / "bad.json"
    d.write_text(json.dumps({"regex": [["only-one-element"]]}), encoding="utf-8")
    with pytest.raises(ValueError):
        Normalizer(d)
