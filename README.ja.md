# subdub

字幕から、動画にサンプル単位で同期する吹き替え音声を作ります。長尺でもズレが蓄積しません。

*[English README](README.md)*

```bash
pip install subdub[all]
subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
```

このコマンド一つで、字幕の取得・音声合成・尺合わせ・プレイヤー生成・ブラウザ起動まで行います。動画はミュートされ、生成した音声が同期再生されます。

---

## 何を解決するのか

素朴に作ると破綻します。字幕1行ずつ合成して繋ぐと、訳文の尺が原語と違うぶん、長引いた行が次を押し出します。10分も経てば数十秒ずれます。

subdub は問題を2つに分けます。

**開始位置** — 各ブロックを必ず字幕の絶対タイムコードに書き込みます。前が何秒溢れても次は定刻に始まるので、**誤差が伝播する経路自体が存在しません**。補正しているのではなく、構造的に起こり得ません。

**長さ** — 劣化の少ない順に3段階で枠に収めます。

| 段階 | 手法 | 劣化 |
|---|---|---|
| 1 | 前後の無音をトリム | なし |
| 2 | **文中のポーズを優先的に圧縮** | ほぼなし |
| 3 | **WSOLA** で残りを吸収 | 圧縮率に比例 |

肝は段階2です。無音を削るのは音声本体を潰すより遥かに聞こえません。先にここで稼ぐことでWSOLAの圧縮率を1.0付近に保て、アーティファクトが最小になります。

実際の17分の動画では、ポーズ圧縮だけで**57秒**を吸収し、平均圧縮率は1.23倍に収まりました。

なお音声が枠より短い場合、引き伸ばしません。字幕の枠は「締切」であって「埋めるべき尺」ではないからです。

---

## インストール

```bash
pip install "subdub[all]"    # YouTube URL対応（yt-dlp込み）
pip install subdub           # 字幕ファイルのみ
```

開発版を直接入れる場合:

```bash
pip install "subdub[all] @ git+https://github.com/kokiaugust24th-coder/subdub.git"
```

Python 3.10以上。Windows / macOS / Linux で動きます。

既定の `edge` バックエンドは Microsoft Edge のニューラル音声を使います。無料・APIキー不要・全OS対応ですが、**合成時にテキストがMicrosoftのサーバへ送られます**。完全オフラインが必要なら `--backend sapi`（Windows標準のSAPI5、音質は大きく劣ります）。

---

## 使い方

### YouTubeのURLから

```bash
subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
```

先に利用可能な字幕を確認できます。

```bash
subdub langs "https://www.youtube.com/watch?v=VIDEO_ID"
```

人手翻訳の字幕を自動的に優先します。機械翻訳より質が高いことが多いためです。

### 字幕ファイルから

```bash
subdub dub movie.ja.srt --video-id VIDEO_ID
subdub serve out
```

`.srt` / `.vtt` / YouTube `.json3` に対応。

### まず試聴する

長編は数分かかります。冒頭だけ作って音質を確かめてください。

```bash
subdub dub movie.ja.srt --range 0:00-1:30 -o preview.wav
```

### 音声を選ぶ

```bash
subdub voices --lang ja
subdub dub movie.srt --voice ja-JP-KeitaNeural
```

### 同期を検証する

```bash
subdub dub movie.srt --verify
```

各ブロックの音声をマスタートラックと相互相関させ、実際に何サンプル目に置かれたかを測ります。閾値による立ち上がり検出と違い、**語頭の音素に左右されません**（破裂音は鋭く、無声摩擦音は緩やかに立ち上がるため、閾値検出では実際にはズレていなくても数十msの誤差に見えてしまいます）。

期待される出力: `PASS  最大ズレ 0.000 ms`

---

## コマンド

| コマンド | 用途 |
|---|---|
| `subdub dub <url\|file>` | 吹き替え音声を生成 |
| `subdub serve [dir]` | 生成済みプレイヤーを配信 |
| `subdub voices [--lang ja]` | 利用可能な音声を一覧 |
| `subdub langs <url>` | 動画の字幕言語を調べる |
| `subdub verify <wav> <fitted>` | 配置精度を検証 |

### `dub` の主なオプション

| オプション | 既定 | 意味 |
|---|---|---|
| `--backend` | `edge` | `edge`（ニューラル）/ `sapi`（オフライン・Windows） |
| `--voice` | バックエンド毎 | 音声名 |
| `--max-compress` | `1.6` | WSOLA最大圧縮率。上げるほど収まるが聞き苦しくなる |
| `--target-rms` | `0.10` | ブロック間で揃える音量 |
| `--fade-ms` | `8.0` | 境界フェード長。クリック音の除去 |
| `--merge-gap` | `0.35` | この間隔以内の字幕を1文に連結 |
| `--range` | — | 時間範囲を限定 例 `1:00-2:30` |
| `--dict` | 同梱辞書 | 発音辞書 |

---

## 発音辞書

ニューラルTTSでも専門用語や固有名詞は読み間違えます。日本語は特に顕著です（漢字の読みが文脈依存で曖昧なため）。**YouTubeの自動吹き替えには読みを直す手段がありません**が、subdub にはあります。

```json
{
  "regex":   [["\\[[^\\]]*\\]", ""],
              ["([a-zA-Z])\\s*\\^\\s*2", "\\1の2乗"]],
  "literal": {"dx": "ディーエックス", "導関数": "どうかんすう"}
}
```

`regex` を上から順に適用し、その後 `literal` を長いキーから適用します。

---

## サマリの読み方

```
ポーズ圧縮で吸収: 57.0 秒
WSOLA圧縮       : 96/145 （平均 1.23倍 / 最大 1.60倍）
枠に収まらず    : 5 ブロック（最大 0.53 秒超過）
```

- **平均圧縮率が1.3を超える** — 字幕の情報密度が高すぎます。`--max-compress` を上げるか、聞き取りやすさを諦めるかの選択になります
- **収まらないブロックが1割超** — その字幕は吹き替えに向いていません

溢れたブロックは、次のブロックと単純加算せずクロスフェードします（二人が同時に喋るのを防ぐため）。次のブロックは定刻に始まります。

---

## ライブラリとして使う

```python
from subdub import load_subtitles, build_blocks, make_backend, build_track, write_wav

cues   = load_subtitles("movie.ja.srt")
blocks = build_blocks(cues)
result = build_track(blocks, make_backend("edge", "ja-JP-NanamiNeural"))
write_wav("dub.wav", result.samples, result.sample_rate)
print(result.summary())
```

TTSエンジンの追加は `Backend` のメソッドを1つ実装するだけです。同期処理はエンジンに依存しません。

---

## 限界

**同期は解決しましたが、同期と明瞭度のトレードオフは残ります。** 訳文が原語より本質的に長い区間では、何かを犠牲にするしかありません。subdub は `--max-compress` まで圧縮し、それ以上は聞き取れなくなるより溢れさせる方を選びます。YouTubeはこれをもっと手前で解いています——**翻訳の段階で尺に収まる訳文を生成させる**——が、既存の字幕を入力にする限りその手は使えません。

**画面依存の語りは苦手です。** 「この形は」「ここの傾きに注目」といった解説動画では情報が画面側にあるため、完璧に同期していても字幕を読むほうが速い場合があります。

**`edge` バックエンドはネットワークが必要**で、テキストがMicrosoftに送信されます。

---

## 類似ツール

同種のツールが既にいくつかあります。用途によってはそちらが適します。

- **[Edge-TTS-Subtitle-Dubbing](https://github.com/fr0stb1rd/Edge-TTS-Subtitle-Dubbing)** — 最も近い。Edge TTS + サンプル単位のtime-slot filling。`audiostretchy` と `librosa` を使用。FFmpeg必須
- **[Auto-Synced-Translated-Dubs](https://github.com/RafaelGodoyEbert/Auto-Synced-Translated-Dubs-with-UI)** — 翻訳工程とGUI付き
- ブラウザ完結型: [SpeechGen](https://speechgen.io/en/subs/), [FreeTTS](https://freetts.org/srt), [Voicertool](https://voicertool.com/subs)

subdub の差分は、ポーズ優先圧縮（圧縮率を低く保てる）、発音辞書、配置検証機構、FFmpeg不要の4点です。

---

## ライセンス

MIT。[LICENSE](LICENSE) を参照してください。
