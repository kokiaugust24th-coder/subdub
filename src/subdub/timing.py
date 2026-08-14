"""尺合わせと音声整形。

吹き替えの同期は2つの独立した問題に分かれる。

  開始位置 — 常に字幕の絶対タイムコードに置く（assemble 側の責務）。
             前が何秒溢れても次は定刻に始まるので誤差が伝播しない。

  長さ     — 割り当て枠にちょうど収める。ここが本モジュールの責務。

長さ合わせは劣化の少ない順に3段階で行う。

  1. trim_silence    TTSが前後に付ける無音を除去（劣化なし）
  2. compress_pauses 文中のポーズを優先的に詰める（ほぼ劣化なし）
  3. wsola           残りをWSOLAで吸収（圧縮率に比例して劣化）

先に1・2で稼ぐことでWSOLAの圧縮率を1.0付近に保てる＝アーティファクトが最小になる。
WSOLA (Waveform Similarity based Overlap-Add) は波形の相関が最大になる位置を
探して重ねるため、ピッチを変えずに伸縮できる。
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

__all__ = [
    "FitInfo", "fit_duration", "polish", "trim_silence",
    "compress_pauses", "wsola", "apply_fades", "normalize_loudness",
    "to_float", "to_int16",
]


def to_float(a: np.ndarray) -> np.ndarray:
    return a.astype(np.float32) / 32768.0


def to_int16(a: np.ndarray) -> np.ndarray:
    return np.clip(a * 32768.0, -32768, 32767).astype(np.int16)


def _envelope(x: np.ndarray, sr: int, win_ms: float) -> np.ndarray:
    """短窓の移動RMS。単発のノイズで誤判定しないための平滑化。"""
    w = max(1, int(sr * win_ms / 1000))
    return np.sqrt(np.convolve(x.astype(np.float64) ** 2,
                               np.ones(w) / w, mode="same"))


# --------------------------------------------------------------------------
# 1. 無音トリム
# --------------------------------------------------------------------------

def trim_silence(x: np.ndarray, sr: int, thresh_db: float = -42.0,
                 keep_ms: float = 6.0, env_ms: float = 2.0) -> np.ndarray:
    """前後の無音を落とす。keep_ms だけ余韻を残す。

    フレーム単位で探すとフレーム長が精度の下限になるので、2msエンベロープで
    サンプル単位に境界を求める。これで発話開始が字幕の時刻とほぼ厳密に一致する。
    """
    if len(x) == 0:
        return x
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        return x[:0]

    idx = np.flatnonzero(_envelope(x, sr, env_ms) > peak * 10 ** (thresh_db / 20))
    if idx.size == 0:
        return x[:0]

    keep = int(sr * keep_ms / 1000)
    return x[max(0, int(idx[0]) - keep):min(len(x), int(idx[-1]) + 1 + keep)]


# --------------------------------------------------------------------------
# 2. ポーズ圧縮
# --------------------------------------------------------------------------

def compress_pauses(x: np.ndarray, sr: int, target_len: int,
                    thresh_db: float = -42.0, min_pause_ms: float = 130.0,
                    floor_ms: float = 60.0) -> tuple[np.ndarray, float]:
    """文中の無音を短縮して全体長を target_len に近づける。

    音声本体には触れないので劣化がない。戻り値は (処理後, 削れた秒数)。
    """
    need = len(x) - target_len
    if need <= 0 or len(x) == 0:
        return x, 0.0

    quiet = _envelope(x, sr, 20.0) <= float(np.max(np.abs(x))) * 10 ** (thresh_db / 20)

    # 無音の連続区間を求める
    edges = np.diff(quiet.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1) + 1)
    if quiet[0]:
        starts.insert(0, 0)
    if quiet[-1]:
        ends.append(len(quiet))

    min_pause = int(sr * min_pause_ms / 1000)
    floor = int(sr * floor_ms / 1000)
    runs = [(s, e) for s, e in zip(starts, ends) if e - s >= min_pause]
    if not runs:
        return x, 0.0

    slack = sum(max(0, (e - s) - floor) for s, e in runs)
    if slack <= 0:
        return x, 0.0

    ratio = min(1.0, need / slack)  # 必要な分だけ削る
    pieces, prev, removed = [], 0, 0
    for s, e in runs:
        pieces.append(x[prev:s])
        cut = int(max(0, (e - s) - floor) * ratio)
        pieces.append(x[s:e - cut] if cut > 0 else x[s:e])
        removed += cut
        prev = e
    pieces.append(x[prev:])
    return np.concatenate(pieces), removed / sr


# --------------------------------------------------------------------------
# 3. WSOLA
# --------------------------------------------------------------------------

def wsola(x: np.ndarray, rate: float, sr: int,
          frame_ms: float = 46.0, tol_ms: float = 10.0) -> np.ndarray:
    """ピッチを保ったまま時間軸を伸縮する。rate>1 で短縮、<1 で伸長。"""
    if len(x) == 0 or abs(rate - 1.0) < 1e-4:
        return x.copy()

    N = max(64, int(sr * frame_ms / 1000) & ~1)
    Hs = N // 2
    Ha = max(1, int(round(Hs * rate)))
    tol = int(sr * tol_ms / 1000)
    if len(x) < N * 2:
        return x.copy()

    win = np.hanning(N + 1)[:N].astype(np.float32)
    n_out = max(N, int(round(len(x) / rate)))
    n_frames = max(1, (n_out - N) // Hs + 1)

    xp = np.concatenate([x, np.zeros(N + Ha * 2 + tol * 2 + Hs, dtype=np.float32)])
    y = np.zeros(n_out + N, dtype=np.float32)
    wsum = np.zeros(n_out + N, dtype=np.float32)

    delta = 0
    for m in range(n_frames):
        ana = max(0, min(m * Ha + delta, len(xp) - N - 1))
        o = m * Hs
        y[o:o + N] += xp[ana:ana + N] * win
        wsum[o:o + N] += win

        # 「このフレームの Hs 先」に最も似た波形を次の分析位置とする
        tmpl = xp[ana + Hs:ana + Hs + N]
        nxt = (m + 1) * Ha
        lo, hi = max(0, nxt - tol), min(len(xp) - N - 1, nxt + tol)
        if hi > lo and len(tmpl) == N:
            region = xp[lo:hi + N]
            delta = (int(np.argmax(np.correlate(region, tmpl, "valid"))) + lo - nxt
                     if len(region) >= N else 0)
        else:
            delta = 0

    return (y / np.maximum(wsum, 1e-6))[:n_out]


# --------------------------------------------------------------------------
# 整形
# --------------------------------------------------------------------------

def apply_fades(x: np.ndarray, sr: int, fade_ms: float = 8.0) -> np.ndarray:
    """境界に極短いフェードを掛けてクリック音を消す。

    波形の途中で切ると振幅が不連続になり「ブツッ」と鳴る。数msなら
    聴感上は無音と区別がつかないので副作用がない。
    """
    if len(x) == 0:
        return x
    n = min(int(sr * fade_ms / 1000), len(x) // 2)
    if n < 2:
        return x
    y = x.copy()
    ramp = (0.5 - 0.5 * np.cos(np.linspace(0, np.pi, n))).astype(np.float32)
    y[:n] *= ramp
    y[-n:] *= ramp[::-1]
    return y


def normalize_loudness(x: np.ndarray, target_rms: float = 0.10,
                       thresh_db: float = -42.0,
                       peak_ceiling: float = 0.95) -> np.ndarray:
    """有声部のRMSを揃える。

    無音込みで測るとポーズの多いブロックほど過剰に増幅されるため、
    しきい値を超えるサンプルだけを見る。
    """
    if len(x) == 0:
        return x
    peak = float(np.max(np.abs(x)))
    if peak <= 0:
        return x
    voiced = x[np.abs(x) > peak * 10 ** (thresh_db / 20)]
    if voiced.size == 0:
        return x
    rms = float(np.sqrt(np.mean(voiced.astype(np.float64) ** 2)))
    if rms <= 0:
        return x
    return (x * min(target_rms / rms, peak_ceiling / peak)).astype(np.float32)


def polish(x: np.ndarray, sr: int, fade_ms: float = 8.0,
           target_rms: float = 0.10) -> np.ndarray:
    """配置直前の仕上げ。音量を揃えてから境界のクリックを消す。"""
    return apply_fades(normalize_loudness(x, target_rms), sr, fade_ms)


# --------------------------------------------------------------------------
# 統合
# --------------------------------------------------------------------------

@dataclass(slots=True)
class FitInfo:
    natural: float = 0.0       # トリム後の自然長(秒)
    pause_saved: float = 0.0   # ポーズ圧縮で稼いだ秒数
    wsola_ratio: float = 1.0   # 適用した圧縮率
    final: float = 0.0         # 最終長(秒)
    overflow: float = 0.0      # 枠を超えた分(秒)
    capped: bool = False       # 圧縮上限に当たったか


def fit_duration(x: np.ndarray, sr: int, target_len: int,
                 max_compress: float = 1.6, pause_floor_ms: float = 60.0,
                 do_trim: bool = True) -> tuple[np.ndarray, FitInfo]:
    """音声を target_len サンプルちょうどに収める。

    短い場合は引き伸ばさない。字幕の枠は «締切» であって «埋めるべき尺» ではなく、
    無理に伸ばすと間延びして不自然になるため、自然長のまま置いて残りは無音にする。
    """
    info = FitInfo()
    if do_trim:
        x = trim_silence(x, sr)
    info.natural = len(x) / sr

    if len(x) == 0 or target_len <= 0:
        info.final = len(x) / sr
        return x, info

    if len(x) <= target_len:
        info.final = len(x) / sr
        return x, info

    x2, saved = compress_pauses(x, sr, target_len, floor_ms=pause_floor_ms)
    info.pause_saved = saved
    if len(x2) <= target_len:
        info.final = len(x2) / sr
        return x2, info

    need = len(x2) / target_len
    ratio = min(need, max_compress)
    info.capped = need > max_compress
    info.wsola_ratio = ratio

    y = wsola(x2, ratio, sr)
    if not info.capped:  # サンプル単位で厳密に合わせる
        y = (y[:target_len] if len(y) > target_len else
             np.concatenate([y, np.zeros(target_len - len(y), dtype=np.float32)]))

    info.final = len(y) / sr
    info.overflow = max(0.0, (len(y) - target_len) / sr)
    return y, info
