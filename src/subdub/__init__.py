"""subdub — 字幕から、動画にサンプル単位で同期する吹き替え音声を作る。

基本的な使い方（ライブラリとして）:

    from subdub import load_subtitles, build_blocks, make_backend, build_track

    cues   = load_subtitles("movie.ja.srt")
    blocks = build_blocks(cues)
    result = build_track(blocks, make_backend("edge", "ja-JP-NanamiNeural"))
    write_wav("dub.wav", result.samples, result.sample_rate)
"""

from __future__ import annotations

__version__ = "1.0.0"

from .backends import BackendError, make_backend
from .blocks import Block, build as build_blocks
from .core import DubResult, build_track, write_report, write_wav
from .subtitles import Cue, load as load_subtitles
from .text import Normalizer
from .timing import FitInfo, fit_duration
from .verify import check_placement

__all__ = [
    "__version__",
    "Cue", "load_subtitles",
    "Block", "build_blocks",
    "Normalizer",
    "FitInfo", "fit_duration",
    "DubResult", "build_track", "write_wav", "write_report",
    "make_backend", "BackendError",
    "check_placement",
]
