"""YouTubeから字幕を取得する（yt-dlp を利用）。

YouTubeの字幕APIは署名付きリクエストが必要になっており、URLを直接叩いても
空が返る。実用的な取得手段は yt-dlp なので、それを薄く包む。
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

__all__ = ["is_url", "video_id", "fetch_subtitles", "available_langs"]

_ID = re.compile(r"(?:v=|/shorts/|youtu\.be/|/embed/)([A-Za-z0-9_-]{11})")


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "www."))


def video_id(url: str) -> str:
    m = _ID.search(url)
    if not m:
        raise ValueError(
            f"YouTubeの動画IDを取り出せませんでした: {url}\n"
            "  例: https://www.youtube.com/watch?v=XXXXXXXXXXX")
    return m.group(1)


def _ensure_ytdlp() -> None:
    try:
        import yt_dlp  # noqa: F401
    except ImportError:
        raise RuntimeError(
            "yt-dlp が入っていません。URLから字幕を取得するには必要です。\n"
            "  pip install yt-dlp\n"
            "  （あるいは字幕ファイルを自分で用意して渡してください）") from None


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "yt_dlp", *args],
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace")


def available_langs(url: str) -> tuple[list[str], list[str]]:
    """(人手翻訳の言語, 自動生成の言語) を返す。"""
    _ensure_ytdlp()
    r = _run(["--list-subs", "--skip-download", url])
    manual, auto, section = [], [], None
    for line in r.stdout.splitlines():
        low = line.lower()
        if "automatic caption" in low:
            section = "auto"
            continue
        if "available subtitles" in low:
            section = "manual"
            continue
        if not section or line.startswith("Language") or not line.strip():
            continue
        code = line.split()[0]
        if re.fullmatch(r"[A-Za-z0-9_-]+", code):
            (auto if section == "auto" else manual).append(code)
    return manual, auto


def fetch_subtitles(url: str, lang: str = "ja", out_dir: str | Path | None = None,
                    auto: bool | None = None) -> Path:
    """字幕をSRTで取得してパスを返す。

    auto=None なら人手翻訳を優先し、無ければ自動生成にフォールバックする。
    人手翻訳のほうが機械翻訳より質が高いことが多い。
    """
    _ensure_ytdlp()
    out_dir = Path(out_dir or tempfile.mkdtemp(prefix="subdub_subs_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    vid = video_id(url)

    modes = ([("--write-sub", False)] if auto is False else
             [("--write-auto-sub", True)] if auto is True else
             [("--write-sub", False), ("--write-auto-sub", True)])

    tried = []
    for flag, is_auto in modes:
        r = _run([flag, "--sub-lang", lang, "--sub-format", "srt",
                  "--convert-subs", "srt", "--skip-download",
                  "-o", str(out_dir / f"{vid}.%(ext)s"), url])
        hits = sorted(out_dir.glob(f"{vid}*.srt"))
        if hits:
            return hits[0]
        tried.append(("自動生成" if is_auto else "人手翻訳",
                      (r.stderr or r.stdout).strip().splitlines()[-1:]))

    manual, auto_langs = available_langs(url)
    raise RuntimeError(
        f"言語 '{lang}' の字幕を取得できませんでした。\n"
        f"  人手翻訳で利用可能: {', '.join(manual) or 'なし'}\n"
        f"  自動生成で利用可能: {', '.join(auto_langs[:12]) or 'なし'}"
        + (" ..." if len(auto_langs) > 12 else ""))
