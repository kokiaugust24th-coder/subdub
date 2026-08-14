"""同期精度の検証。

配置は「各ブロックの音声を、マスタートラックのどこに置いたか」で決まる。
それを相互相関で直接測る。閾値による立ち上がり検出と違い、語頭の音素に
左右されない（破裂音は鋭く、無声摩擦音は緩やかに立ち上がるため、
閾値検出では音素ごとに数十msの差が出てしまう）。
"""

from __future__ import annotations

import json
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

__all__ = ["PlacementCheck", "check_placement"]


@dataclass(slots=True)
class PlacementCheck:
    rows: list[tuple[int, float, int, float]]  # (i, 期待秒, ラグsmp, ラグms)
    worst_ms: float
    checked: int
    sample_rate: int

    @property
    def passed(self) -> bool:
        return self.worst_ms <= 1.0


def _read(path: Path) -> tuple[np.ndarray, int]:
    with wave.open(str(path), "rb") as w:
        return (np.frombuffer(w.readframes(w.getnframes()),
                              dtype="<i2").astype(np.float64),
                w.getframerate())


def check_placement(master_wav: str | Path, fitted_dir: str | Path,
                    search_ms: float = 60.0) -> PlacementCheck:
    master, sr = _read(Path(master_wav))
    places = json.loads((Path(fitted_dir) / "placements.json")
                        .read_text(encoding="utf-8"))
    W = int(sr * search_ms / 1000)

    rows: list[tuple[int, float, int, float]] = []
    worst = 0.0
    for pl in places:
        i, off = pl["i"], pl["offset"]
        seg, _ = _read(Path(fitted_dir) / f"{i:05d}.wav")
        if len(seg) < 64 or np.max(np.abs(seg)) == 0:
            continue
        lo, hi = max(0, off - W), min(len(master), off + len(seg) + W)
        region = master[lo:hi]
        if len(region) < len(seg):
            continue
        lag = int(np.argmax(np.correlate(region, seg, "valid"))) + lo - off
        lag_ms = lag * 1000.0 / sr
        worst = max(worst, abs(lag_ms))
        rows.append((i, off / sr, lag, lag_ms))

    return PlacementCheck(rows, worst, len(rows), sr)
