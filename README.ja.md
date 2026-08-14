# subdub

[![CI](https://github.com/kokiaugust24th-coder/subdub/actions/workflows/ci.yml/badge.svg)](https://github.com/kokiaugust24th-coder/subdub/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.10+-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

**外国語の動画を、日本語音声で見られるようにするツールです。**

字幕から音声を作り、動画にぴったり合わせて再生します。字幕を目で追わずに済みます。

*[English README](README.md)*

---

## 30秒で試す

```bash
pip install "subdub[all]"

subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
```

これだけです。ブラウザが開いて、動画が日本語音声で再生されます。

<details>
<summary>実行中はこんな表示になります（クリックで展開）</summary>

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

  音声      : out\dub.wav
  レポート  : out\report.csv
  プレイヤー: out\player.html

  http://localhost:8000/player.html
```

</details>

> **いきなり全部作らないでください。** 長い動画は数分かかります。まず下の「試聴」で
> 声を確かめてから本番を回すのがおすすめです。

---

## よくある使い方

### まず声を試聴する（推奨）

冒頭90秒だけ作ります。1分もかかりません。

```bash
subdub dub "動画URL" --lang ja --range 0:00-1:30 -o preview.wav
```

`out/preview.wav` を再生して、声と読み方が許容できるか確認してください。

### 声を変える

```bash
subdub voices --lang ja        # 使える声を一覧
subdub dub "動画URL" --voice ja-JP-KeitaNeural   # 男性の声にする
```

日本語は `ja-JP-NanamiNeural`（女性・既定）と `ja-JP-KeitaNeural`（男性）が使えます。

### 手元の字幕ファイルから作る

```bash
subdub dub movie.ja.srt --video-id VIDEO_ID
subdub serve out
```

`.srt` `.vtt` `.json3` に対応しています。

### あとでもう一度見る

一度作れば、次からは再生するだけです。

```bash
subdub serve out
```

### 字幕があるか先に調べる

```bash
subdub langs "動画URL"
```

```
人手翻訳（推奨・機械翻訳より質が高いことが多い）:
  en, ja, ko, zh

自動生成:
  af, ak, am, ar, ...
```

人手翻訳があればそちらが自動で使われます。

---

## コマンド早見表

| やりたいこと | コマンド |
|---|---|
| 動画を吹き替える | `subdub dub "URL" --lang ja --serve` |
| 作ったものを再生する | `subdub serve out` |
| 声の一覧を見る | `subdub voices --lang ja` |
| 字幕の言語を調べる | `subdub langs "URL"` |
| 同期の精度を測る | `subdub dub ... --verify` |

---

## 困ったときは

<details open>
<summary><b>字幕が見つからないと言われる</b></summary>

その言語の字幕が動画に無い可能性があります。まず確認してください。

```bash
subdub langs "動画URL"
```

一覧に無ければ、別の言語を `--lang` に指定するか、自分で字幕ファイルを用意します。
</details>

<details>
<summary><b>単語の読み方が間違っている</b></summary>

専門用語や固有名詞はニューラル音声でも読み間違えます。辞書で直せます。

自分の辞書ファイルを作ります。

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

`literal` は単純置換、`regex` は正規表現置換です。長い語から優先して置換されます。
</details>

<details>
<summary><b>プレイヤーを開いても音が出ない・シークすると音がズレる</b></summary>

`player.html` をダブルクリックで開いたり、`python -m http.server` で配信していませんか。
どちらも動きません。**必ず `subdub serve` を使ってください。**

- ダブルクリック（`file://`）→ YouTubeの再生機能が動作しません
- `python -m http.server` → HTTP Range に非対応で、音声のシークができません

```bash
subdub serve out
```
</details>

<details>
<summary><b>音声が早口すぎる／聞き取りにくい</b></summary>

日本語訳が原語より長い区間では、枠に収めるため音声を圧縮しています。
圧縮率を下げると聞きやすくなりますが、その分はみ出します。

```bash
subdub dub "URL" --max-compress 1.3     # 既定は1.6。下げるほど自然
```

実行後のサマリで「平均1.3倍」を超えていたら、その字幕は情報密度が高すぎます。
</details>

<details>
<summary><b>音量が小さい／大きい</b></summary>

```bash
subdub dub "URL" --target-rms 0.15      # 既定は0.10。上げると大きくなる
```

プレイヤー画面の音量スライダーでも調整できます。
</details>

<details>
<summary><b>ネットにつながらない環境で使いたい</b></summary>

Windowsなら標準搭載の音声でオフライン生成できます。ただし**音質は大きく落ちます**
（古い世代のエンジンのため、抑揚が平坦で読み間違いも増えます）。

```bash
subdub dub movie.srt --backend sapi
```

macOS / Linux にはオフライン用のバックエンドがまだありません。
</details>

<details>
<summary><b>合成が途中で失敗する</b></summary>

既定の `edge` バックエンドはネットワークを使います。接続を確認してください。
自動で3回まで再試行します。

音声名を間違えている可能性もあります。`subdub voices` で正しい名前を確認してください。
</details>

---

## 仕組み（興味があれば）

素朴に作ると必ず失敗します。字幕1行ずつ音声にして順番に繋ぐと、訳文の尺が原語と違うぶん、
長引いた行が次を押し出します。**10分後には数十秒ずれます。**

subdub は問題を2つに分けて解きます。

### 開始位置は絶対にずらさない

各ブロックを字幕のタイムコード位置に直接書き込みます。前のブロックが何秒溢れても、
次は定刻に始まります。**誤差が伝播する経路そのものが存在しません。**
補正しているのではなく、構造的に起こり得ません。

### 長さは劣化の少ない順に詰める

| 段階 | 手法 | 劣化 |
|---|---|---|
| 1 | 前後の無音をトリム | なし |
| 2 | **文中のポーズを圧縮** | ほぼなし |
| 3 | **WSOLA** で残りを吸収 | 圧縮率に比例 |

肝は段階2です。無音を削るのは音声本体を潰すより遥かに聞こえません。
先にここで稼ぐことで、WSOLAの圧縮率を1.0付近に保てます。

実際の17分の動画では、**ポーズ圧縮だけで57秒を吸収**し、平均圧縮率は1.23倍に収まりました。

なお音声が枠より短くても引き伸ばしません。字幕の枠は「締切」であって
「埋めるべき尺」ではないからです。

### 検証できる

```bash
subdub dub movie.srt --verify
```

```
配置検証  : PASS  最大ズレ 0.000 ms （145 ブロック）
```

各ブロックの音声をマスタートラックと相互相関させ、実際に何サンプル目に置かれたかを
直接測ります。語頭の音素に左右されない測り方です（破裂音は鋭く、無声摩擦音は
緩やかに立ち上がるため、音量の閾値で測ると実際はズレていなくても誤差に見えます）。

---

## オプション一覧

<details>
<summary>クリックで展開</summary>

| オプション | 既定 | 意味 |
|---|---|---|
| `--lang` | `ja` | 字幕の言語コード |
| `-o, --out` | `dub.wav` | 出力音声のファイル名 |
| `--outdir` | `out` | 出力先ディレクトリ |
| `--backend` | `edge` | `edge`（ニューラル）/ `sapi`（オフライン・Windows） |
| `--voice` | 自動 | 音声名 |
| `--serve` | — | 生成後そのまま配信してブラウザを開く |
| `--port` | `8000` | 配信ポート |
| `--verify` | — | 生成後に配置精度を検証 |
| `--max-compress` | `1.6` | 最大圧縮率。下げると自然、上げると枠に収まる |
| `--target-rms` | `0.10` | 音量 |
| `--fade-ms` | `8.0` | 境界フェード長（クリック音の除去） |
| `--merge-gap` | `0.35` | この間隔以内の字幕を1文に連結 |
| `--max-block` | `12.0` | 連結後の1ブロック最大長 |
| `--range` | — | 時間範囲を限定 例 `1:00-2:30` |
| `--dict` | 同梱辞書 | 発音辞書 |
| `--report` | `report.csv` | 同期レポート |

</details>

---

## インストール

```bash
pip install "subdub[all]"    # YouTube URL対応（推奨）
pip install subdub           # 字幕ファイルのみ
```

開発版:

```bash
pip install "subdub[all] @ git+https://github.com/kokiaugust24th-coder/subdub.git"
```

Python 3.10以上。Windows / macOS / Linux で動作を確認しています。

既定の `edge` バックエンドは Microsoft Edge のニューラル音声を使います。無料・APIキー不要ですが、
**合成時にテキストがMicrosoftのサーバへ送信されます。**

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

TTSエンジンの追加は `Backend` のメソッドを1つ実装するだけです。同期処理には手を入れる必要がありません。

---

## 限界

**同期は解決しましたが、同期と明瞭度のトレードオフは残ります。** 訳文が原語より本質的に長い区間では、
何かを犠牲にするしかありません。subdub は `--max-compress` まで圧縮し、それ以上は
聞き取れなくなるより溢れさせる方を選びます。

YouTubeはこれをもっと手前で解いています——**翻訳の段階で尺に収まる訳文を生成させる**——が、
既存の字幕を入力にする限りその手は使えません。

**画面依存の語りは苦手です。** 「この形は」「ここの傾きに注目」といった解説動画では
情報が画面側にあるため、完璧に同期していても字幕を読むほうが速い場合があります。

---

## 類似ツール

同種のツールが既にあります。用途によってはそちらが適します。

- **[Edge-TTS-Subtitle-Dubbing](https://github.com/fr0stb1rd/Edge-TTS-Subtitle-Dubbing)** — 最も近い。FFmpeg必須
- **[Auto-Synced-Translated-Dubs](https://github.com/RafaelGodoyEbert/Auto-Synced-Translated-Dubs-with-UI)** — 翻訳工程とGUI付き
- ブラウザ完結型: [SpeechGen](https://speechgen.io/en/subs/), [FreeTTS](https://freetts.org/srt), [Voicertool](https://voicertool.com/subs)

subdub の差分は、ポーズ優先圧縮・発音辞書・配置検証・FFmpeg不要の4点です。

---

## ライセンス

MIT
