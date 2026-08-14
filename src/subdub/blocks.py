"""字幕キューを、読み上げ単位のブロックへまとめる。

字幕は画面の表示幅に合わせて文の途中で改行されている。そのまま1行ずつ
読ませると細切れの不自然な抑揚になるため、途切れていない連続キューを
1文に連結してから合成する。

各ブロックの「割り当て枠」は次のブロックの開始時刻までとする。字幕の表示終了
ではなく次の発話開始までを使うことで、字幕間の «間» も発話に使える。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .subtitles import Cue
from .text import Normalizer

__all__ = ["Block", "build"]

SENT_END = tuple("。．.!！?？")
LAST_BUDGET = float("inf")


@dataclass(slots=True)
class Block:
    start: float
    text: str
    budget: float = LAST_BUDGET
    info: object = None
    meta: dict = field(default_factory=dict)


def build(cues: list[Cue], normalizer: Normalizer | None = None,
          merge_gap: float = 0.35, max_block: float = 12.0) -> list[Block]:
    norm = normalizer or Normalizer()
    blocks: list[Block] = []

    buf: list[str] = []
    b_start = b_end = 0.0

    def flush() -> None:
        if buf:
            t = norm.apply(" ".join(buf))
            if t:
                blocks.append(Block(b_start, t))

    for c in cues:
        t = c.text.strip()
        if not t:
            continue
        if not buf:
            b_start, b_end, buf = c.start, c.end, [t]
            continue

        continues = not "".join(buf).rstrip().endswith(SENT_END)
        if (c.start - b_end) <= merge_gap and continues \
                and (c.end - b_start) <= max_block:
            buf.append(t)
            b_end = c.end
        else:
            flush()
            b_start, b_end, buf = c.start, c.end, [t]
    flush()

    for i, b in enumerate(blocks):
        b.budget = (blocks[i + 1].start - b.start) if i + 1 < len(blocks) \
            else LAST_BUDGET
    return blocks
