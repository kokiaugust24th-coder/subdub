"""尺合わせと整形のテスト。合成エンジンに依存しない部分を合成波形で検証する。"""

from __future__ import annotations

import numpy as np
import pytest

from subdub.timing import (apply_fades, compress_pauses, fit_duration,
                           normalize_loudness, trim_silence, wsola)

SR = 24000


def tone(sec: float, freq: float = 200.0, amp: float = 0.5) -> np.ndarray:
    t = np.arange(int(SR * sec)) / SR
    return (amp * np.sin(2 * np.pi * freq * t)).astype(np.float32)


def silence(sec: float) -> np.ndarray:
    return np.zeros(int(SR * sec), dtype=np.float32)


# --- trim ---------------------------------------------------------------

def test_trim_removes_leading_silence():
    x = np.concatenate([silence(0.5), tone(1.0), silence(0.5)])
    y = trim_silence(x, SR)
    # 前後の無音が落ちて、ほぼ音の長さになる（keep_ms分だけ余る）
    assert len(y) / SR == pytest.approx(1.0, abs=0.03)


def test_trim_all_silence_returns_empty():
    assert len(trim_silence(silence(1.0), SR)) == 0


def test_trim_empty_input():
    assert len(trim_silence(np.zeros(0, dtype=np.float32), SR)) == 0


# --- pause compression --------------------------------------------------

def test_compress_pauses_shrinks_only_pauses():
    x = np.concatenate([tone(0.5), silence(1.0), tone(0.5)])
    target = int(SR * 1.5)
    y, saved = compress_pauses(x, SR, target)
    assert saved > 0
    assert len(y) < len(x)
    assert len(y) >= target * 0.9      # 目標付近まで詰まる


def test_compress_pauses_noop_when_already_short():
    x = tone(0.5)
    y, saved = compress_pauses(x, SR, len(x) + 100)
    assert saved == 0.0
    assert len(y) == len(x)


def test_compress_pauses_keeps_floor():
    """ポーズを完全には潰さない（floor_ms を残す）。"""
    x = np.concatenate([tone(0.3), silence(2.0), tone(0.3)])
    y, _ = compress_pauses(x, SR, int(SR * 0.6), floor_ms=100.0)
    assert len(y) / SR > 0.6 + 0.09    # floor が残るぶん目標より長い


# --- wsola --------------------------------------------------------------

@pytest.mark.parametrize("rate", [1.2, 1.5, 2.0])
def test_wsola_compresses_to_expected_length(rate):
    x = tone(2.0)
    y = wsola(x, rate, SR)
    assert len(y) / (len(x) / rate) == pytest.approx(1.0, abs=0.05)


def test_wsola_preserves_pitch():
    """時間を縮めても基本周波数が変わらないこと（リサンプリングとの違い）。"""
    f0 = 200.0
    y = wsola(tone(2.0, f0), 1.5, SR)
    spec = np.abs(np.fft.rfft(y * np.hanning(len(y))))
    peak = np.fft.rfftfreq(len(y), 1 / SR)[int(np.argmax(spec))]
    assert peak == pytest.approx(f0, rel=0.05)


def test_wsola_identity_rate():
    x = tone(0.5)
    assert np.array_equal(wsola(x, 1.0, SR), x)


def test_wsola_short_input_untouched():
    x = tone(0.005)
    assert len(wsola(x, 1.5, SR)) == len(x)


# --- polish -------------------------------------------------------------

def test_fades_zero_the_edges():
    y = apply_fades(np.ones(SR, dtype=np.float32), SR, fade_ms=10.0)
    assert abs(y[0]) < 1e-3 and abs(y[-1]) < 1e-3
    assert y[len(y) // 2] == pytest.approx(1.0)


def test_normalize_matches_target_rms():
    y = normalize_loudness(tone(1.0, amp=0.02), target_rms=0.1)
    assert float(np.sqrt(np.mean(y.astype(np.float64) ** 2))) == pytest.approx(
        0.1, rel=0.15)


def test_normalize_never_clips():
    y = normalize_loudness(tone(1.0, amp=0.9), target_rms=0.9)
    assert np.max(np.abs(y)) <= 1.0


# --- fit_duration -------------------------------------------------------

def test_fit_exact_when_within_compress_cap():
    x = np.concatenate([silence(0.1), tone(1.2), silence(0.1)])
    target = int(SR * 1.0)
    y, info = fit_duration(x, SR, target, max_compress=1.6)
    assert len(y) == target          # サンプル単位で一致
    assert not info.capped
    assert info.overflow == 0.0


def test_fit_reports_overflow_when_capped():
    x = tone(5.0)
    target = int(SR * 1.0)           # 5倍圧縮は上限を超える
    y, info = fit_duration(x, SR, target, max_compress=1.6)
    assert info.capped
    assert info.overflow > 0
    assert len(y) > target


def test_fit_does_not_stretch_short_audio():
    """枠は «締切» であって «埋めるべき尺» ではない。"""
    x = tone(0.5)
    y, info = fit_duration(x, SR, int(SR * 3.0))
    assert len(y) == pytest.approx(len(x), abs=SR * 0.05)
    assert info.wsola_ratio == 1.0


def test_fit_prefers_pause_compression_over_wsola():
    """ポーズで足りるならWSOLAを使わない（劣化を避ける）。"""
    x = np.concatenate([tone(0.4), silence(1.2), tone(0.4)])
    y, info = fit_duration(x, SR, int(SR * 1.2), max_compress=1.6)
    assert info.pause_saved > 0
    assert info.wsola_ratio == pytest.approx(1.0)


def test_fit_empty_audio():
    y, info = fit_duration(np.zeros(0, dtype=np.float32), SR, SR)
    assert len(y) == 0 and info.natural == 0.0
