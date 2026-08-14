"""コマンドラインインターフェース。

いちばん短い使い方:

    subdub dub "https://www.youtube.com/watch?v=..." --lang ja

字幕の取得・合成・同期・プレイヤー生成・配信までを一度に行う。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .backends import BACKENDS, BackendError, make_backend
from .blocks import build as build_blocks
from .core import build_track, write_report, write_wav
from .text import Normalizer, default_dict_path
from .subtitles import load as load_subs, ts_to_sec

# --------------------------------------------------------------------------
# 表示ヘルパ
# --------------------------------------------------------------------------

def _err(msg: str) -> int:
    print(f"\nエラー: {msg}\n", file=sys.stderr)
    return 1


def _mmss(sec: float) -> str:
    m, s = divmod(sec, 60)
    return f"{int(m)}:{s:05.2f}"


class _Progress:
    """1行を書き換える簡易プログレス表示。"""

    def __init__(self, quiet: bool):
        self.quiet = quiet
        self.label = ""

    def stage(self, name: str, total: int) -> None:
        if self.quiet:
            return
        self.label = {"synth": "音声合成", "fit": "尺合わせ・配置"}.get(name, name)
        if name == "fit":
            print(f"\r  {self.label} ...", end="", flush=True)

    def __call__(self, done: int, total: int) -> None:
        if self.quiet:
            return
        bar_w = 24
        filled = int(bar_w * done / max(1, total))
        print(f"\r  {self.label} [{'█' * filled}{'·' * (bar_w - filled)}] "
              f"{done}/{total}", end="", flush=True)
        if done >= total:
            print()


def _print_summary(res, quiet: bool) -> None:
    if quiet:
        return
    s = res.summary()
    print(f"\n  長さ            : {s['duration'] / 60:.1f} 分"
          f"（{s['blocks']} ブロック）")
    print(f"  ポーズ圧縮で吸収: {s['pause_saved']:.1f} 秒")
    if s["stretched"]:
        print(f"  WSOLA圧縮       : {s['stretched']}/{s['blocks']} "
              f"（平均 {s['avg_ratio']:.2f}倍 / 最大 {s['max_ratio']:.2f}倍）")
    if s["capped"]:
        print(f"  枠に収まらず    : {s['capped']} ブロック"
              f"（最大 {s['max_overflow']:.2f} 秒超過）")
        print("     ※ 超過しても次は定刻開始なのでズレは伝播しません。")
        worst = sorted((b for b in res.blocks if b.info),
                       key=lambda b: -b.info.overflow)[:3]
        for b in worst:
            if b.info.overflow <= 0.05:
                break
            print(f"       {_mmss(b.start)}  +{b.info.overflow:.2f}秒  "
                  f"{b.text[:28]}…")
    else:
        print("  枠に収まらず    : なし（全ブロック収まりました）")


# --------------------------------------------------------------------------
# dub
# --------------------------------------------------------------------------

def cmd_dub(a: argparse.Namespace) -> int:
    outdir = Path(a.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    quiet = a.quiet
    video_id = a.video_id

    # --- 入力: URL なら字幕を取得、そうでなければファイル ---
    src = a.source
    if src and (src.startswith(("http://", "https://")) or "youtube.com" in src
                or "youtu.be" in src):
        from . import youtube
        try:
            video_id = video_id or youtube.video_id(src)
            if not quiet:
                print(f"字幕を取得中（{a.lang}）...")
            sub_path = youtube.fetch_subtitles(src, a.lang, outdir)
            if not quiet:
                print(f"  {sub_path.name}")
        except (RuntimeError, ValueError) as e:
            return _err(str(e))
    else:
        sub_path = Path(src)

    # --- 字幕 → ブロック ---
    try:
        cues = load_subs(sub_path)
    except (FileNotFoundError, ValueError) as e:
        return _err(str(e))

    if a.range:
        lo, _, hi = a.range.partition("-")
        lo_s = ts_to_sec(lo) if lo else 0.0
        hi_s = ts_to_sec(hi) if hi else float("inf")
        cues = [c for c in cues if lo_s <= c.start < hi_s]
    if a.limit:
        cues = cues[:a.limit]
    if not cues:
        return _err("指定範囲に字幕がありません。")

    dict_path = a.dict if a.dict else default_dict_path(a.lang)
    try:
        norm = Normalizer(dict_path)
    except (FileNotFoundError, ValueError) as e:
        return _err(str(e))

    blocks = build_blocks(cues, norm, a.merge_gap, a.max_block)
    if not quiet:
        print(f"字幕 {len(cues)} キュー → {len(blocks)} ブロック")

    # --- 合成 ---
    try:
        backend = make_backend(a.backend, a.voice)
    except BackendError as e:
        return _err(str(e))

    if not quiet:
        print(f"エンジン: {backend.name} / {backend.voice}")

    prog = _Progress(quiet)
    out_wav = outdir / a.out
    try:
        res = build_track(
            blocks, backend,
            max_compress=a.max_compress, pause_floor_ms=a.pause_floor_ms,
            do_trim=not a.no_trim, fade_ms=a.fade_ms, target_rms=a.target_rms,
            dump_dir=(outdir / "fitted") if a.verify or a.dump_fitted else None,
            progress=prog, on_stage=prog.stage)
    except BackendError as e:
        return _err(str(e))

    write_wav(out_wav, res.samples, res.sample_rate)
    _print_summary(res, quiet)
    print(f"\n  音声      : {out_wav}")

    if a.report:
        rp = outdir / a.report
        write_report(res, rp)
        print(f"  レポート  : {rp}")

    # --- 検証 ---
    if a.verify:
        from .verify import check_placement
        chk = check_placement(out_wav, outdir / "fitted")
        mark = "PASS" if chk.passed else "FAIL"
        print(f"  配置検証  : {mark}  最大ズレ {chk.worst_ms:.3f} ms "
              f"（{chk.checked} ブロック）")

    # --- プレイヤー ---
    if video_id:
        from .player import write_player
        page = write_player(outdir / "player.html", out_wav.name, video_id)
        print(f"  プレイヤー: {page}")
        if a.serve:
            from .player import serve
            serve(outdir, a.port, page.name, open_browser=not a.no_open)
        elif not quiet:
            print(f"\n  再生するには:  subdub serve {outdir}")
    elif not quiet:
        print("\n  ヒント: --video-id を指定すると同期プレイヤーも生成します。")
    return 0


# --------------------------------------------------------------------------
# その他のサブコマンド
# --------------------------------------------------------------------------

def cmd_serve(a: argparse.Namespace) -> int:
    from .player import serve
    d = Path(a.directory)
    if not (d / "player.html").exists():
        return _err(f"player.html が見つかりません: {d}\n"
                    "  先に subdub dub を実行してください。")
    serve(d, a.port, "player.html", open_browser=not a.no_open)
    return 0


def cmd_voices(a: argparse.Namespace) -> int:
    kinds = [a.backend] if a.backend else list(BACKENDS)
    for kind in kinds:
        cls = BACKENDS[kind]
        ok, why = cls.available()
        print(f"\n=== {kind} ===")
        if not ok:
            print(f"  利用不可: {why.splitlines()[0]}")
            continue
        try:
            voices = cls.list_voices(a.lang)
        except Exception as e:  # noqa: BLE001
            print(f"  取得できませんでした: {e}")
            continue
        if not voices:
            print(f"  '{a.lang}' に該当する音声がありません。")
        for v in voices:
            print(f"  {v}")
    return 0


def cmd_verify(a: argparse.Namespace) -> int:
    from .verify import check_placement
    try:
        chk = check_placement(a.wav, a.fitted)
    except (FileNotFoundError, OSError) as e:
        return _err(str(e))
    print(f"{'#':>4}  {'期待位置(秒)':>12}  {'ラグ':>16}")
    for i, exp, lag, ms in chk.rows:
        flag = "" if abs(ms) <= 1.0 else "  <-- 許容超過"
        print(f"{i:>4}  {exp:>12.3f}  {lag:>+6d} smp ({ms:>+6.2f} ms){flag}")
    print(f"\n検証 {chk.checked} ブロック / 最大ズレ {chk.worst_ms:.3f} ms")
    print("判定:", "PASS  配置はサンプル単位で正確" if chk.passed else "FAIL")
    return 0 if chk.passed else 1


def cmd_langs(a: argparse.Namespace) -> int:
    from . import youtube
    try:
        manual, auto = youtube.available_langs(a.url)
    except RuntimeError as e:
        return _err(str(e))
    print("人手翻訳（推奨・機械翻訳より質が高いことが多い）:")
    print("  " + (", ".join(manual) if manual else "なし"))
    print("\n自動生成:")
    print("  " + (", ".join(auto) if auto else "なし"))
    return 0


# --------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="subdub",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description="字幕から、動画にサンプル単位で同期する吹き替え音声を作る。",
        epilog="""例:
  subdub dub "https://www.youtube.com/watch?v=VIDEO_ID" --lang ja --serve
  subdub dub movie.ja.srt --video-id VIDEO_ID
  subdub dub movie.srt --range 0:00-1:30 -o preview.wav   # まず試聴
  subdub voices --lang ja
  subdub langs "https://www.youtube.com/watch?v=VIDEO_ID"
""")
    p.add_argument("--version", action="version", version=f"subdub {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    # dub
    d = sub.add_parser("dub", help="吹き替え音声を生成する",
                       formatter_class=argparse.ArgumentDefaultsHelpFormatter)
    d.add_argument("source", help="YouTubeのURL、または字幕ファイル(.srt/.vtt/.json3)")
    d.add_argument("--lang", default="ja", help="字幕の言語コード")
    d.add_argument("-o", "--out", default="dub.wav", help="出力音声のファイル名")
    d.add_argument("--outdir", default="out", help="出力先ディレクトリ")
    d.add_argument("--backend", default="edge", choices=list(BACKENDS),
                   help="合成エンジン（edge=ニューラル / sapi=オフライン・Windows専用）")
    d.add_argument("--voice", default="", help="音声名（既定はバックエンドごと）")
    d.add_argument("--video-id", default="", help="プレイヤー用のYouTube動画ID")
    d.add_argument("--serve", action="store_true", help="生成後そのまま配信して開く")
    d.add_argument("--port", type=int, default=8000)
    d.add_argument("--no-open", action="store_true", help="ブラウザを自動で開かない")
    d.add_argument("--report", default="report.csv", help="同期レポートCSV（空で無効）")
    d.add_argument("--verify", action="store_true", help="生成後に配置精度を検証する")
    d.add_argument("--dump-fitted", action="store_true", help="尺合わせ後の音声を残す")
    d.add_argument("--dict", default="", help="発音辞書JSON（既定は言語ごとの同梱辞書）")
    d.add_argument("--max-compress", type=float, default=1.6,
                   help="WSOLAの最大圧縮率。上げるほど枠に収まるが明瞭度が落ちる")
    d.add_argument("--pause-floor-ms", type=float, default=60.0,
                   help="ポーズ圧縮後に残す最小無音長")
    d.add_argument("--fade-ms", type=float, default=8.0,
                   help="境界フェード長。クリック音の除去用")
    d.add_argument("--target-rms", type=float, default=0.10,
                   help="ブロック間で揃える音量")
    d.add_argument("--merge-gap", type=float, default=0.35,
                   help="この間隔以内の字幕を1文に連結する")
    d.add_argument("--max-block", type=float, default=12.0,
                   help="連結後の1ブロック最大長")
    d.add_argument("--no-trim", action="store_true", help="前後の無音を除去しない")
    d.add_argument("--range", default="", help="処理する時間範囲 例 0:00-1:30")
    d.add_argument("--limit", type=int, default=0, help="先頭Nキューだけ処理")
    d.add_argument("-q", "--quiet", action="store_true")
    d.set_defaults(func=cmd_dub)

    # serve
    s = sub.add_parser("serve", help="生成済みのプレイヤーを配信する")
    s.add_argument("directory", nargs="?", default="out")
    s.add_argument("--port", type=int, default=8000)
    s.add_argument("--no-open", action="store_true")
    s.set_defaults(func=cmd_serve)

    # voices
    v = sub.add_parser("voices", help="利用可能な音声を一覧表示する")
    v.add_argument("--backend", choices=list(BACKENDS), default=None)
    v.add_argument("--lang", default="", help="言語で絞り込む 例 ja")
    v.set_defaults(func=cmd_voices)

    # langs
    lg = sub.add_parser("langs", help="動画で利用できる字幕言語を調べる")
    lg.add_argument("url")
    lg.set_defaults(func=cmd_langs)

    # verify
    vf = sub.add_parser("verify", help="配置精度を検証する")
    vf.add_argument("wav")
    vf.add_argument("fitted", help="--dump-fitted / --verify で出来た fitted ディレクトリ")
    vf.set_defaults(func=cmd_verify)

    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except KeyboardInterrupt:
        print("\n中断しました。", file=sys.stderr)
        return 130
    except BackendError as e:
        return _err(str(e))


if __name__ == "__main__":
    sys.exit(main())
