"""生成の中核。合成 → 尺合わせ → 絶対配置 → ミックスダウン。"""

from __future__ import annotations

import csv
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .backends import Backend
from .blocks import Block
from .timing import fit_duration, polish, to_float, to_int16

__all__ = ["DubResult", "build_track", "write_wav", "write_report"]


@dataclass(slots=True)
class DubResult:
    samples: np.ndarray
    sample_rate: int
    blocks: list[Block]
    placements: list[dict]

    @property
    def duration(self) -> float:
        return len(self.samples) / self.sample_rate

    def summary(self) -> dict:
        infos = [b.info for b in self.blocks if b.info]
        stretched = [i for i in infos if i.wsola_ratio > 1.001]
        capped = [i for i in infos if i.capped]
        return {
            "blocks": len(self.blocks),
            "duration": self.duration,
            "pause_saved": sum(i.pause_saved for i in infos),
            "stretched": len(stretched),
            "avg_ratio": (sum(i.wsola_ratio for i in stretched) / len(stretched)
                          if stretched else 1.0),
            "max_ratio": max((i.wsola_ratio for i in stretched), default=1.0),
            "capped": len(capped),
            "max_overflow": max((i.overflow for i in infos), default=0.0),
        }


def _read_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        if w.getsampwidth() != 2 or w.getnchannels() != 1:
            raise RuntimeError(f"想定外のWAV形式です: {path}")
        return to_float(np.frombuffer(w.readframes(w.getnframes()), dtype="<i2"))


def write_wav(path: str | Path, samples: np.ndarray, sr: int) -> None:
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(to_int16(samples).tobytes())


def build_track(blocks: list[Block], backend: Backend, *,
                max_compress: float = 1.6, pause_floor_ms: float = 60.0,
                do_trim: bool = True, fade_ms: float = 8.0,
                target_rms: float = 0.10, tail: float = 1.0,
                dump_dir: Path | None = None, progress=None,
                on_stage=None) -> DubResult:
    sr = backend.sample_rate

    with tempfile.TemporaryDirectory(prefix="subdub_") as tmp:
        cue_dir = Path(tmp)
        if on_stage:
            on_stage("synth", len(blocks))
        backend.render([{"id": i, "text": b.text} for i, b in enumerate(blocks)],
                       cue_dir, progress)

        # 出力長の上限を見積もる。枠は最終ブロックで無限大なので必ず実測長を使う。
        natural: list[float] = []
        for i, b in enumerate(blocks):
            with wave.open(str(backend.out_path(cue_dir, i)), "rb") as w:
                natural.append(w.getnframes() / float(w.getframerate()))
        total = max(b.start + n for b, n in zip(blocks, natural)) + tail
        master = np.zeros(int(total * sr) + 1, dtype=np.float32)

        if on_stage:
            on_stage("fit", len(blocks))

        placements: list[dict] = []
        prev_end = 0
        if dump_dir:
            dump_dir = Path(dump_dir)
            dump_dir.mkdir(parents=True, exist_ok=True)

        for i, b in enumerate(blocks):
            x = _read_wav(backend.out_path(cue_dir, i))
            budget = (len(master) if b.budget == float("inf")
                      else max(1, int(b.budget * sr)))
            y, info = fit_duration(x, sr, budget, max_compress=max_compress,
                                   pause_floor_ms=pause_floor_ms, do_trim=do_trim)
            b.info = info
            y = polish(y, sr, fade_ms=fade_ms, target_rms=target_rms)

            # 同期の要: 常に絶対時刻へ置く。誤差を後続へ持ち越さない。
            off = int(round(b.start * sr))
            n = min(len(y), len(master) - off)
            if n > 0:
                # 前が溢れて重なる場合、単純加算だと二人が同時に喋る。
                # 重なりをクロスフェードして前を引きながら次を立ち上げる。
                if off < prev_end:
                    ov = min(prev_end - off, n)
                    if ov > 1:
                        r = np.linspace(1.0, 0.0, ov, dtype=np.float32)
                        master[off:off + ov] *= r
                        y = y.copy()
                        y[:ov] *= 1.0 - r
                master[off:off + n] += y[:n]
                prev_end = off + n

            if dump_dir:
                write_wav(dump_dir / f"{i:05d}.wav", y, sr)
            placements.append({"i": i, "offset": off, "len": int(len(y))})

        if dump_dir:
            import json
            (dump_dir / "placements.json").write_text(
                json.dumps(placements), encoding="utf-8")

    np.clip(master, -1.0, 1.0, out=master)
    return DubResult(master, sr, blocks, placements)


def write_report(result: DubResult, path: str | Path) -> None:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["#", "開始(秒)", "開始", "枠(秒)", "自然長(秒)",
                    "ポーズ削減(秒)", "WSOLA率", "最終長(秒)", "超過(秒)",
                    "上限到達", "本文"])
        for i, b in enumerate(result.blocks):
            n = b.info
            mm, ss = divmod(b.start, 60)
            w.writerow([i, f"{b.start:.2f}", f"{int(mm)}:{ss:05.2f}",
                        "" if b.budget == float("inf") else f"{b.budget:.2f}",
                        f"{n.natural:.2f}", f"{n.pause_saved:.2f}",
                        f"{n.wsola_ratio:.3f}", f"{n.final:.2f}",
                        f"{n.overflow:.2f}", "YES" if n.capped else "", b.text])
