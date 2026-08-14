"""字幕ファイルの読み込み。SRT / WebVTT / YouTube json3 に対応する。"""

from __future__ import annotations

import html
import json
import re
from dataclasses import dataclass
from pathlib import Path

__all__ = ["Cue", "load", "parse_srt_vtt", "parse_json3", "ts_to_sec"]


@dataclass(slots=True)
class Cue:
    start: float
    end: float
    text: str

    @property
    def dur(self) -> float:
        return self.end - self.start


def ts_to_sec(ts: str) -> float:
    """`HH:MM:SS,mmm` / `MM:SS.mmm` / `1:23` を秒に変換する。"""
    ts = ts.strip().replace(",", ".")
    parts = ts.split(":")
    if len(parts) == 3:
        h, m, s = parts
    elif len(parts) == 2:
        h, m, s = "0", parts[0], parts[1]
    elif len(parts) == 1:
        h, m, s = "0", "0", parts[0]
    else:
        raise ValueError(f"タイムスタンプを解釈できません: {ts!r}")
    return int(h) * 3600 + int(m) * 60 + float(s)


_TAG = re.compile(r"<[^>]+>")
_ARROW = re.compile(
    r"(\d{1,3}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,3}:\d{2}[.,]\d{1,3})"
    r"\s*-->\s*"
    r"(\d{1,3}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,3}:\d{2}[.,]\d{1,3})")


def _clean(text: str) -> str:
    return html.unescape(_TAG.sub("", text))


def parse_srt_vtt(raw: str) -> list[Cue]:
    raw = raw.lstrip("﻿")
    raw = re.sub(r"^WEBVTT.*?(\n\n|\Z)", "", raw, flags=re.S)
    raw = re.sub(r"^NOTE\b.*?(\n\n|\Z)", "", raw, flags=re.M | re.S)

    cues: list[Cue] = []
    for block in re.split(r"\n\s*\n", raw):
        block = block.strip()
        if not block:
            continue
        lines = block.splitlines()
        idx = next((i for i, ln in enumerate(lines) if _ARROW.search(ln)), None)
        if idx is None:
            continue
        m = _ARROW.search(lines[idx])
        text = " ".join(l.strip() for l in lines[idx + 1:] if l.strip())
        text = _clean(text).strip()
        if text:
            cues.append(Cue(ts_to_sec(m.group(1)), ts_to_sec(m.group(2)), text))
    return cues


def parse_json3(raw: str) -> list[Cue]:
    data = json.loads(raw)
    cues: list[Cue] = []
    for ev in data.get("events", []):
        segs = ev.get("segs")
        if not segs:
            continue
        text = _clean("".join(s.get("utf8", "") for s in segs))
        text = text.replace("\n", " ").strip()
        if not text:
            continue
        start = ev.get("tStartMs", 0) / 1000.0
        cues.append(Cue(start, start + ev.get("dDurationMs", 0) / 1000.0, text))
    return cues


def load(path: str | Path) -> list[Cue]:
    """拡張子と中身から形式を判定して読み込む。"""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"字幕ファイルが見つかりません: {p}")
    raw = p.read_text(encoding="utf-8-sig", errors="replace")

    if p.suffix.lower() in (".json3", ".json") or raw.lstrip().startswith("{"):
        cues = parse_json3(raw)
    else:
        cues = parse_srt_vtt(raw)

    if not cues:
        raise ValueError(
            f"字幕を1件も読み取れませんでした: {p}\n"
            "SRT / WebVTT / YouTube json3 のいずれかである必要があります。")
    cues.sort(key=lambda c: c.start)
    return cues
