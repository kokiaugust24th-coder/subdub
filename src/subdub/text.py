"""読み上げ用のテキスト正規化と発音辞書。

TTSは字幕の装飾（[音楽] など）をそのまま読んでしまうし、数式記号や
専門用語の読みも外しやすい。ここで読み上げ前に整える。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

__all__ = ["Normalizer", "default_dict_path"]

DATA_DIR = Path(__file__).parent / "data"


def default_dict_path(lang: str = "ja") -> Path | None:
    p = DATA_DIR / f"pronounce.{lang}.json"
    return p if p.exists() else None


class Normalizer:
    """辞書に基づく置換。`regex` を順に適用してから `literal` を長い順に適用する。"""

    def __init__(self, dict_path: str | Path | None = None):
        self.regex: list[tuple[re.Pattern, str]] = []
        self.literal: dict[str, str] = {}

        if dict_path:
            p = Path(dict_path)
            if not p.exists():
                raise FileNotFoundError(f"発音辞書が見つかりません: {p}")
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise ValueError(f"発音辞書のJSONが不正です: {p}\n  {e}") from e

            for i, entry in enumerate(d.get("regex", [])):
                if not isinstance(entry, list) or len(entry) != 2:
                    raise ValueError(
                        f"{p}: regex[{i}] は [パターン, 置換後] の形式にしてください")
                try:
                    self.regex.append((re.compile(entry[0]), entry[1]))
                except re.error as e:
                    raise ValueError(f"{p}: regex[{i}] が不正です: {e}") from e

            self.literal = {k: v for k, v in d.get("literal", {}).items()
                            if not k.startswith("_")}

        self._keys = sorted(self.literal, key=len, reverse=True)

    def apply(self, text: str) -> str:
        for pat, rep in self.regex:
            text = pat.sub(rep, text)
        for k in self._keys:
            if k in text:
                text = text.replace(k, self.literal[k])
        return re.sub(r"\s+", " ", text).strip()
