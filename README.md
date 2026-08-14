# subdub

[![CI](https://github.com/kokiaugust24th-coder/subdub/actions/workflows/ci.yml/badge.svg)](https://github.com/kokiaugust24th-coder/subdub/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**Watch foreign-language videos with spoken audio in your language.**

subdub turns subtitles into a dubbed audio track and keeps it locked to the video, so you can listen instead of reading.

*[日本語版 README](README.ja.md)*

---

## Try it in 30 seconds

```bash
pip install "subdub[all]"

subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
```

That's it. Your browser opens and the video plays with the generated audio in sync.

<details>
<summary>What you'll see while it runs (click to expand)</summary>

```
字幕を取得中（ja）...
  VIDEO_ID.ja.srt
字幕 319 キュー → 145 ブロック
エンジン: edge / ja-JP-NanamiNeural
  音声合成 [████████████████████████] 145/145
  尺合わせ・配置 ...

  長さ            : 16.8 分（145 ブロック）
  ポーズ圧縮で吸収: 57.0 秒
  WSOLA圧縮       : 96/145 （平均 1.23倍 / 最大 1.60倍）
  枠に収まらず    : 5 ブロック（最大 0.53 秒超過）

  音声      : out/dub.wav
  プレイヤー: out/player.html

  http://localhost:8000/player.html
```

</details>

> **Don't render a whole video first.** Long videos take several minutes. Preview a
> slice to check the voice before committing (see below).

---

## Common tasks

### Preview the voice first (recommended)

Renders the first 90 seconds. Takes under a minute.

```bash
subdub dub "VIDEO_URL" --lang ja --range 0:00-1:30 -o preview.wav
```

Play `out/preview.wav` and decide whether the voice and pronunciation work for you.

### Change the voice

```bash
subdub voices --lang ja                          # list what's available
subdub dub "VIDEO_URL" --voice ja-JP-KeitaNeural  # use a male voice
```

Any language Edge TTS supports works — `subdub voices --lang de`, `--lang es`, and so on.

### Use your own subtitle file

```bash
subdub dub movie.ja.srt --video-id VIDEO_ID
subdub serve out
```

Supports `.srt`, `.vtt`, and `.json3`.

### Watch it again later

Once generated, just serve it:

```bash
subdub serve out
```

### Check which subtitles exist

```bash
subdub langs "VIDEO_URL"
```

Human-translated tracks are preferred automatically — they're usually much better than machine translation.

---

## Command reference

| Goal | Command |
|---|---|
| Dub a video | `subdub dub "URL" --lang ja --serve` |
| Replay what you made | `subdub serve out` |
| List voices | `subdub voices --lang ja` |
| List subtitle languages | `subdub langs "URL"` |
| Measure sync accuracy | `subdub dub ... --verify` |

---

## Troubleshooting

<details open>
<summary><b>"Subtitles not found"</b></summary>

The video may not have subtitles in that language. Check first:

```bash
subdub langs "VIDEO_URL"
```

If your language isn't listed, pick another with `--lang`, or supply your own subtitle file.
</details>

<details>
<summary><b>A word is pronounced wrong</b></summary>

Neural TTS still trips over technical terms and proper nouns. Fix them with a dictionary:

```json
{
  "literal": {
    "導関数": "どうかんすう",
    "dx": "ディーエックス"
  }
}
```

```bash
subdub dub "URL" --dict mydict.json
```

`literal` does plain replacement (longest key first); `regex` does pattern replacement.
</details>

<details>
<summary><b>No sound, or audio desyncs when I seek</b></summary>

Did you open `player.html` by double-clicking, or serve it with `python -m http.server`?
Neither works. **Always use `subdub serve`.**

- Double-clicking (`file://`) — the YouTube player API won't run
- `python -m http.server` — no HTTP Range support, so the browser can't seek the audio

```bash
subdub serve out
```
</details>

<details>
<summary><b>Speech is too fast / hard to follow</b></summary>

Where the translation runs longer than the original, audio gets compressed to fit.
Lower the cap for more natural speech, at the cost of some blocks overflowing:

```bash
subdub dub "URL" --max-compress 1.3     # default 1.6; lower is more natural
```

If the summary reports an average ratio above ~1.3, the subtitles are simply dense.
</details>

<details>
<summary><b>Volume is too quiet or too loud</b></summary>

```bash
subdub dub "URL" --target-rms 0.15      # default 0.10
```

There's also a volume slider in the player.
</details>

<details>
<summary><b>I need this to work offline</b></summary>

On Windows you can use the built-in SAPI voices. **Quality is substantially worse** —
it's an older engine with flat prosody and more mispronunciations.

```bash
subdub dub movie.srt --backend sapi
```

There's no offline backend for macOS or Linux yet.
</details>

<details>
<summary><b>Synthesis fails partway through</b></summary>

The default `edge` backend needs network access. It retries up to three times automatically.
Also check the voice name with `subdub voices`.
</details>

---

## How it works

The naive approach always fails. Synthesize each subtitle line, concatenate them, and every
line that runs long pushes the next one later. **Ten minutes in, you're tens of seconds off.**

subdub splits this into two problems.

### Start positions never move

Every block is written at its absolute timecode. If one block overruns, the next still
starts exactly on time. **There is no path for error to accumulate** — drift isn't corrected
for, it's structurally impossible.

### Duration is fitted cheapest-degradation-first

| Stage | Method | Cost |
|---|---|---|
| 1 | Trim leading/trailing silence | none |
| 2 | **Compress pauses inside the speech** | negligible |
| 3 | **WSOLA time-stretch** for the remainder | proportional to ratio |

Stage 2 is what makes it sound good. Shrinking silence is far less audible than compressing
speech, so buying time there first keeps the WSOLA ratio near 1.0 where artifacts are minimal.

On a real 17-minute video, **pause compression alone absorbed 57 seconds**, leaving an
average stretch ratio of just 1.23×.

Short audio is never padded out to fill its slot. A subtitle's time slot is a *deadline*,
not a duration to fill.

### You can verify it

```bash
subdub dub movie.srt --verify
```

```
配置検証  : PASS  最大ズレ 0.000 ms （145 ブロック）
```

This cross-correlates each fitted block against the master track to find where it actually
landed. It doesn't rely on onset detection, so it's immune to the initial phoneme — a plosive
has a sharp attack while a voiceless fricative ramps up slowly, which would otherwise look
like tens of milliseconds of error that isn't really there.

---

## All options

<details>
<summary>Click to expand</summary>

| Option | Default | Meaning |
|---|---|---|
| `--lang` | `ja` | Subtitle language code |
| `-o, --out` | `dub.wav` | Output audio filename |
| `--outdir` | `out` | Output directory |
| `--backend` | `edge` | `edge` (neural) or `sapi` (offline, Windows) |
| `--voice` | auto | Voice name |
| `--serve` | — | Serve and open the browser when done |
| `--port` | `8000` | Server port |
| `--verify` | — | Check placement accuracy after generating |
| `--max-compress` | `1.6` | Max compression. Lower is more natural |
| `--target-rms` | `0.10` | Loudness |
| `--fade-ms` | `8.0` | Edge fade length (removes boundary clicks) |
| `--merge-gap` | `0.35` | Join subtitle lines closer than this into one sentence |
| `--max-block` | `12.0` | Max length of a merged block |
| `--range` | — | Limit to a time range, e.g. `1:00-2:30` |
| `--dict` | bundled | Pronunciation dictionary |
| `--report` | `report.csv` | Sync report |

</details>

---

## Install

```bash
pip install "subdub[all]"    # with YouTube URL support (recommended)
pip install subdub           # subtitle files only
```

Development version:

```bash
pip install "subdub[all] @ git+https://github.com/kokiaugust24th-coder/subdub.git"
```

Python 3.10+. Tested on Windows, macOS, and Linux.

The default `edge` backend uses Microsoft Edge's neural voices — free and no API key, but
**text is sent to Microsoft's servers** for synthesis.

---

## Library use

```python
from subdub import load_subtitles, build_blocks, make_backend, build_track, write_wav

cues   = load_subtitles("movie.ja.srt")
blocks = build_blocks(cues)
result = build_track(blocks, make_backend("edge", "ja-JP-NanamiNeural"))
write_wav("dub.wav", result.samples, result.sample_rate)
print(result.summary())
```

Adding a TTS engine means implementing one method on `Backend`. The timing pipeline is
entirely engine-agnostic.

---

## Limitations

**Sync is solved; the sync/intelligibility tradeoff is not.** Where the translation genuinely
needs more time than the original, something has to give. subdub compresses up to
`--max-compress`, then lets the block overflow rather than making it unintelligible.

Production systems like YouTube attack this earlier in the pipeline, by asking the translator
for a length-matched rendering — which is out of reach when you start from an existing
subtitle file.

**Screen-dependent narration stays hard.** In lectures that say "this shape here" or "notice
the slope," the information lives on screen. Perfect timing doesn't help if you still have to
look at the subtitles.

---

## Prior art

Several tools solve a similar problem. One of them may suit you better:

- **[Edge-TTS-Subtitle-Dubbing](https://github.com/fr0stb1rd/Edge-TTS-Subtitle-Dubbing)** — closest equivalent. Requires FFmpeg
- **[Auto-Synced-Translated-Dubs](https://github.com/RafaelGodoyEbert/Auto-Synced-Translated-Dubs-with-UI)** — includes translation and a GUI
- Web-based: [SpeechGen](https://speechgen.io/en/subs/), [FreeTTS](https://freetts.org/srt), [Voicertool](https://voicertool.com/subs)

What subdub adds: pause-first compression (which keeps stretch ratios low), a pronunciation
dictionary, a built-in placement verifier, and no FFmpeg dependency.

---

## License

MIT
