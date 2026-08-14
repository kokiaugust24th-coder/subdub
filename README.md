# subdub

Turn subtitles into a dubbed audio track that stays in sync with the video — sample-accurately, with no drift over long runtimes.

*[日本語版 README](README.ja.md)*

```bash
pip install subdub[all]
subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
```

That single command fetches the subtitles, synthesizes speech, fits it to the original timing, builds a player, and opens it in your browser. The video plays muted while the generated track plays in sync.

---

## The problem it solves

The naive approach — synthesize each subtitle line, then concatenate — falls apart quickly. Translated speech rarely takes the same time as the original, so every line that runs long pushes the next one later. After ten minutes you are tens of seconds out of sync.

subdub splits the problem in two:

**Start position.** Every block is written at its absolute timecode. If one block overruns, the next still starts exactly on time. There is no path for error to accumulate — drift is structurally impossible, not merely corrected for.

**Duration.** Each block is fitted to its time slot in three stages, cheapest-degradation first:

| Stage | Method | Cost |
|---|---|---|
| 1 | Trim leading/trailing silence | none |
| 2 | **Compress pauses inside the speech** | negligible |
| 3 | **WSOLA time-stretch** for the remainder | proportional to ratio |

Stage 2 is what makes this sound good. Shrinking silence is far less audible than compressing speech, so buying time there first keeps the WSOLA ratio near 1.0, where artifacts are minimal.

On a real 17-minute video, pause compression alone absorbed **57 seconds** of overflow, leaving an average stretch ratio of just 1.23×.

Short audio is never stretched to fill its slot. A subtitle's time slot is a *deadline*, not a duration to pad.

---

## Install

```bash
pip install subdub[all]      # includes yt-dlp for YouTube URLs
pip install subdub           # subtitle files only
```

Requires Python 3.10+. Works on Windows, macOS, and Linux.

The default `edge` backend uses Microsoft Edge's neural voices — free, no API key, and cross-platform. Note that **text is sent to Microsoft's servers** for synthesis. For fully offline use on Windows, `--backend sapi` uses the built-in SAPI5 voices (much lower quality).

---

## Usage

### From a YouTube URL

```bash
subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
```

Check which subtitle languages exist first:

```bash
subdub langs "https://www.youtube.com/watch?v=VIDEO_ID"
```

Human-translated subtitles are preferred over auto-generated ones automatically — they are usually much better than machine translation.

### From a subtitle file

```bash
subdub dub movie.ja.srt --video-id VIDEO_ID
subdub serve out
```

Supports `.srt`, `.vtt`, and YouTube `.json3`.

### Preview before committing

Rendering a full-length video takes a few minutes. Try a slice first:

```bash
subdub dub movie.ja.srt --range 0:00-1:30 -o preview.wav
```

### Pick a voice

```bash
subdub voices --lang ja
subdub dub movie.srt --voice ja-JP-KeitaNeural
```

### Verify the sync

```bash
subdub dub movie.srt --verify
```

This cross-correlates each fitted block against the master track to measure where it actually landed, in samples. It does not depend on onset detection, so it is unaffected by the initial phoneme — a plosive has a sharp attack while a voiceless fricative ramps up slowly, which would otherwise show tens of milliseconds of apparent error that isn't real.

Expected output: `PASS  最大ズレ 0.000 ms`.

---

## Commands

| Command | Purpose |
|---|---|
| `subdub dub <url\|file>` | Generate the dubbed track |
| `subdub serve [dir]` | Serve a generated player |
| `subdub voices [--lang ja]` | List available voices |
| `subdub langs <url>` | List subtitle languages for a video |
| `subdub verify <wav> <fitted>` | Check placement accuracy |

### Key options for `dub`

| Option | Default | Meaning |
|---|---|---|
| `--backend` | `edge` | `edge` (neural) or `sapi` (offline, Windows) |
| `--voice` | per backend | Voice name |
| `--max-compress` | `1.6` | Max WSOLA ratio. Higher fits more, sounds worse |
| `--target-rms` | `0.10` | Loudness blocks are normalized to |
| `--fade-ms` | `8.0` | Edge fade length, removes boundary clicks |
| `--merge-gap` | `0.35` | Join subtitle lines closer than this into one sentence |
| `--range` | — | Process only a time range, e.g. `1:00-2:30` |
| `--dict` | bundled | Pronunciation dictionary |

---

## Pronunciation dictionary

Neural TTS still mispronounces technical terms and proper nouns — Japanese is especially prone to it, since kanji readings are ambiguous and context-dependent. YouTube's own auto-dubbing offers no way to correct this. subdub does.

Edit the bundled dictionary or supply your own:

```json
{
  "regex":   [["\\[[^\\]]*\\]", ""],
              ["([a-zA-Z])\\s*\\^\\s*2", "\\1の2乗"]],
  "literal": {"dx": "ディーエックス", "導関数": "どうかんすう"}
}
```

`regex` entries apply in order, then `literal` replacements apply longest-key-first.

---

## Reading the summary

```
ポーズ圧縮で吸収: 57.0 秒
WSOLA圧縮       : 96/145 （平均 1.23倍 / 最大 1.60倍）
枠に収まらず    : 5 ブロック（最大 0.53 秒超過）
```

- **Average ratio above ~1.3** — the subtitles are dense for the target language. Either raise `--max-compress` or accept reduced intelligibility.
- **More than ~10% not fitting** — this subtitle track is a poor fit for dubbing.

Blocks that overflow crossfade into the next one rather than playing on top of it, and the next block still starts on time.

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

Adding a TTS engine means implementing one method on `Backend`. The entire timing pipeline is engine-agnostic.

---

## Limitations

**Sync is solved; the sync/intelligibility tradeoff is not.** Where the translation genuinely needs more time than the original, something has to give. subdub compresses up to `--max-compress` and then lets the block overflow rather than making it unintelligible. Production systems like YouTube attack this earlier in the pipeline, by asking the translator for a length-matched rendering — which is out of reach when you start from an existing subtitle file.

**Screen-dependent narration stays hard.** In lectures that say "this shape here" or "notice the slope," the information lives on screen. A dub that is perfectly timed can still be harder to follow than reading the subtitles.

**The `edge` backend needs network access** and sends text to Microsoft.

---

## Prior art

Several tools solve a similar problem, and it is worth checking whether one fits you better:

- **[Edge-TTS-Subtitle-Dubbing](https://github.com/fr0stb1rd/Edge-TTS-Subtitle-Dubbing)** — closest equivalent. Edge TTS with sample-accurate time-slot filling, using `audiostretchy` and `librosa`. Requires FFmpeg.
- **[Auto-Synced-Translated-Dubs](https://github.com/RafaelGodoyEbert/Auto-Synced-Translated-Dubs-with-UI)** — includes translation and a GUI.
- Web-based: [SpeechGen](https://speechgen.io/en/subs/), [FreeTTS](https://freetts.org/srt), [Voicertool](https://voicertool.com/subs).

What subdub adds: pause-first compression (which keeps stretch ratios low), a pronunciation dictionary, a built-in placement verifier, and no FFmpeg dependency.

---

## License

MIT. See [LICENSE](LICENSE).
