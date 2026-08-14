"""音声合成バックエンド。

同期ロジックはエンジンに依存しないので、ここを差し替えるだけで音質を入れ替えられる。

  edge — Microsoft Edge の読み上げニューラル音声。全OSで動く。既定。
         合成のたびにテキストがMicrosoftのサーバへ送られる点に注意。
  sapi — Windows標準のSAPI5。完全オフラインだが旧世代エンジンで抑揚が平坦。

いずれも「モノラル・指定サンプルレートのWAVを {id:05d}.wav として書く」という
同じ契約を満たす。
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

__all__ = ["Backend", "EdgeBackend", "SapiBackend", "make_backend",
           "SAMPLE_RATE", "BackendError"]

SAMPLE_RATE = 24000  # edge-tts のネイティブ
DATA_DIR = Path(__file__).parent / "data"
PS_SCRIPT = DATA_DIR / "tts_render.ps1"


class BackendError(RuntimeError):
    """音声合成に失敗したときの例外。メッセージは利用者向けに具体的にする。"""


def _write_wav(path: Path, x: np.ndarray, sr: int) -> None:
    import soundfile as sf
    sf.write(str(path), x.astype(np.float32), sr, subtype="PCM_16")


def _resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    if src == dst:
        return x
    n = int(round(len(x) * dst / src))
    return np.interp(np.linspace(0, len(x) - 1, n),
                     np.arange(len(x)), x).astype(np.float32)


# --------------------------------------------------------------------------

class Backend:
    name = "base"

    def __init__(self, voice: str = "", sample_rate: int = SAMPLE_RATE):
        self.voice = voice or self.default_voice()
        self.sample_rate = sample_rate

    @classmethod
    def default_voice(cls) -> str:
        raise NotImplementedError

    @staticmethod
    def available() -> tuple[bool, str]:
        """(使えるか, 使えない理由) を返す。"""
        return True, ""

    def render(self, items: list[dict], out_dir: Path,
               progress=None) -> None:
        """items: [{"id": int, "text": str}] を out_dir に合成する。"""
        raise NotImplementedError

    @staticmethod
    def out_path(out_dir: Path, i: int) -> Path:
        return Path(out_dir) / f"{i:05d}.wav"

    def dedupe(self, items: list[dict], out_dir: Path) -> list[dict]:
        """同一テキストは一度だけ合成し、残りはコピーで済ませる。

        繰り返しの多い字幕では合成回数がはっきり減る。
        """
        first: dict[str, int] = {}
        todo: list[dict] = []
        self._copies: list[tuple[int, int]] = []
        for it in items:
            key = hashlib.sha1(it["text"].encode("utf-8")).hexdigest()
            if key in first:
                self._copies.append((first[key], it["id"]))
            else:
                first[key] = it["id"]
                todo.append(it)
        return todo

    def finish_dedupe(self, out_dir: Path) -> None:
        for src, dst in getattr(self, "_copies", []):
            s, d = self.out_path(out_dir, src), self.out_path(out_dir, dst)
            if s.exists():
                shutil.copyfile(s, d)


# --------------------------------------------------------------------------

class EdgeBackend(Backend):
    name = "edge"

    def __init__(self, voice: str = "", sample_rate: int = SAMPLE_RATE,
                 concurrency: int = 5, retries: int = 3):
        super().__init__(voice, sample_rate)
        self.concurrency = concurrency
        self.retries = retries

    @classmethod
    def default_voice(cls) -> str:
        return "ja-JP-NanamiNeural"

    @staticmethod
    def available() -> tuple[bool, str]:
        try:
            import edge_tts  # noqa: F401
        except ImportError:
            return False, ("edge-tts が入っていません。\n"
                           "  pip install edge-tts")
        try:
            import soundfile  # noqa: F401
        except ImportError:
            return False, ("soundfile が入っていません。\n"
                           "  pip install soundfile")
        return True, ""

    def render(self, items: list[dict], out_dir: Path, progress=None) -> None:
        ok, why = self.available()
        if not ok:
            raise BackendError(why)
        todo = self.dedupe(items, out_dir)
        if todo:
            asyncio.run(self._run(todo, Path(out_dir), progress))
        self.finish_dedupe(Path(out_dir))

    async def _run(self, items, out_dir: Path, progress) -> None:
        import edge_tts
        sem = asyncio.Semaphore(self.concurrency)
        done = [0]

        async def one(it: dict) -> None:
            import soundfile as sf
            async with sem:
                last: Exception | None = None
                for attempt in range(self.retries):
                    try:
                        buf = io.BytesIO()
                        comm = edge_tts.Communicate(it["text"], self.voice)
                        async for ch in comm.stream():
                            if ch["type"] == "audio":
                                buf.write(ch["data"])
                        if buf.tell() == 0:
                            raise BackendError("音声データが返りませんでした")
                        buf.seek(0)
                        data, sr = sf.read(buf, dtype="float32", always_2d=False)
                        if data.ndim > 1:
                            data = data.mean(axis=1)
                        _write_wav(self.out_path(out_dir, it["id"]),
                                   _resample(data, sr, self.sample_rate),
                                   self.sample_rate)
                        done[0] += 1
                        if progress:
                            progress(done[0], len(items))
                        return
                    except Exception as e:  # noqa: BLE001
                        last = e
                        await asyncio.sleep(1.0 + attempt * 1.5)
                raise BackendError(
                    f"合成に失敗しました（{self.voice}）: {last}\n"
                    "  ネットワーク接続と音声名を確認してください。\n"
                    "  利用可能な音声: subdub voices")

        await asyncio.gather(*(one(it) for it in items))

    @staticmethod
    def list_voices(locale: str = "") -> list[str]:
        import edge_tts

        async def go():
            vs = await edge_tts.list_voices()
            return [f"{v['ShortName']:30} {v['Gender']:7} {v['Locale']}"
                    for v in sorted(vs, key=lambda v: v["ShortName"])
                    if not locale or v["Locale"].lower().startswith(locale.lower())]

        return asyncio.run(go())


# --------------------------------------------------------------------------

class SapiBackend(Backend):
    name = "sapi"

    @classmethod
    def default_voice(cls) -> str:
        return "Microsoft Haruka Desktop"

    @staticmethod
    def available() -> tuple[bool, str]:
        if platform.system() != "Windows":
            return False, ("sapi バックエンドは Windows 専用です。\n"
                           "  --backend edge を使ってください。")
        if not (shutil.which("powershell") or shutil.which("pwsh")):
            return False, "PowerShell が見つかりません。"
        return True, ""

    def render(self, items: list[dict], out_dir: Path, progress=None) -> None:
        ok, why = self.available()
        if not ok:
            raise BackendError(why)
        todo = self.dedupe(items, out_dir)
        if todo:
            out_dir = Path(out_dir)
            manifest = out_dir / "_manifest.json"
            manifest.write_text(json.dumps(
                [{"text": it["text"], "rate": it.get("rate", 0),
                  "out": str(self.out_path(out_dir, it["id"]))} for it in todo],
                ensure_ascii=False), encoding="utf-8")

            ps = shutil.which("powershell") or shutil.which("pwsh")
            proc = subprocess.run(
                [ps, "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                 "-File", str(PS_SCRIPT), "-Manifest", str(manifest),
                 "-SampleRate", str(self.sample_rate), "-Voice", self.voice],
                capture_output=True, text=True, encoding="utf-8", errors="replace")
            if proc.returncode != 0:
                raise BackendError(
                    f"SAPI合成に失敗しました（{self.voice}）\n"
                    f"  {proc.stderr.strip().splitlines()[-1] if proc.stderr.strip() else ''}\n"
                    "  利用可能な音声: subdub voices --backend sapi")
            if progress:
                progress(len(todo), len(todo))
        self.finish_dedupe(Path(out_dir))

    @staticmethod
    def list_voices(locale: str = "") -> list[str]:
        ok, why = SapiBackend.available()
        if not ok:
            raise BackendError(why)
        ps = shutil.which("powershell") or shutil.which("pwsh")
        script = ("Add-Type -AssemblyName System.Speech;"
                  "(New-Object System.Speech.Synthesis.SpeechSynthesizer)"
                  ".GetInstalledVoices() | %{ $i=$_.VoiceInfo;"
                  '"$($i.Name)|$($i.Culture)|$($i.Gender)" }')
        r = subprocess.run([ps, "-NoProfile", "-Command", script],
                           capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        out = []
        for line in r.stdout.splitlines():
            parts = line.strip().split("|")
            if len(parts) == 3:
                if locale and not parts[1].lower().startswith(locale.lower()):
                    continue
                out.append(f"{parts[0]:30} {parts[2]:7} {parts[1]}")
        return out


# --------------------------------------------------------------------------

BACKENDS = {"edge": EdgeBackend, "sapi": SapiBackend}


def make_backend(kind: str = "edge", voice: str = "",
                 sample_rate: int = SAMPLE_RATE) -> Backend:
    kind = (kind or "edge").lower()
    if kind not in BACKENDS:
        raise BackendError(
            f"未知のバックエンド: {kind}（選択肢: {', '.join(BACKENDS)}）")
    cls = BACKENDS[kind]
    ok, why = cls.available()
    if not ok:
        raise BackendError(why)
    return cls(voice, sample_rate)
