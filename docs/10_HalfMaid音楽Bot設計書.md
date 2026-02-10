# HalfMaid 音楽Bot 設計書

## Context

Rajitan本体とは別プロセスで動作する音楽再生専用のDiscord Bot。Rajitanからの指示をHTTP APIで受け取り、yt-dlp + FFmpeg + discord.py voiceで音楽を再生する。

---

## 1. アーキテクチャ

```
Discord ユーザー
  │
  ├── @らじたん 曲かけて
  │     ↓
  │   Rajitan (AIエージェント)
  │     ↓ music_play ツール
  │   GenericExecutor → music_player_api ハンドラ
  │     ↓ HTTP POST
  │   HalfMaid API (localhost:8001)
  │     ↓
  │   VoiceManager → yt-dlp → FFmpeg → Discord VC
  │
  └── /np, /queue, /skip, /stop（HalfMaidスラッシュコマンド）
        ↓ 直接
      HalfMaid Bot → VoiceManager
```

### プロセス構成

| プロセス | ポート | systemdサービス | 役割 |
|---|---|---|---|
| Rajitan | 8000 (API) | `rajitan` | AIエージェント、WebUI API |
| HalfMaid | 8001 (API) | `halfmaid` | 音楽再生、VC管理 |

## 2. パッケージ構成

```
halfmaid/
  ├── __init__.py
  ├── main.py           エントリーポイント（Bot + FastAPI起動）
  ├── config.py         環境変数から設定読み込み
  ├── bot/
  │   ├── client.py     HalfMaidBot（discord.py Bot、スラッシュコマンド）
  │   └── voice.py      VoiceManager（再生制御、オートプレイ）
  ├── api/
  │   ├── app.py        FastAPIアプリ
  │   └── routes/
  │       └── player.py API エンドポイント群
  ├── queue/
  │   ├── manager.py    QueueManager（ギルドごとのキュー管理）
  │   └── models.py     Track データモデル
  └── utils/
      ├── logger.py     ロガー
      └── ytdlp.py      YtDlpExtractor（検索、抽出、関連動画）
```

## 3. 再生パイプライン

```
1. ユーザーリクエスト（曲名 or URL）
   ↓
2. YtDlpExtractor.extract(query)
   - ytsearch10 で最大10件取得
   - 有効なエントリを順番に試行
   - TrackInfo（title, artist, url, stream_url, duration, thumbnail）を返す
   ↓
3. VoiceManager.play()
   - VCに未接続なら connect()
   - 再生中なら Queue に追加
   - 未再生なら即座に _start_playback()
   ↓
4. _start_playback()
   - FFmpegPCMAudio(stream_url) + PCMVolumeTransformer
   - vc.play(source, after=callback)
   - callback → _play_next()
   ↓
5. _play_next()
   - Queue に次の曲がある → 再生
   - Queue 空 && autoplay=True → _autoplay()
   - Queue 空 && autoplay=False → idle_disconnect タイマー
```

## 4. オートプレイ機能

キューが空になった時、音楽を止めずに関連動画を自動で再生し続ける。

### 仕組み

1. 最後に再生した曲のYouTube URLから関連動画を取得（`YtDlpExtractor.get_related()`）
2. 再生済みURLを `GuildVoiceState.played_urls` で記録し、重複を除外
3. 関連動画が見つからない場合、曲名+アーティスト名で検索にフォールバック
4. stream_url を取得して `_start_playback()` で再生
5. `stop()` 実行時に `played_urls` をクリア（次のセッションは新鮮に）

### 設定

- デフォルト: **ON**（`GuildVoiceState.autoplay = True`）
- Rajitanツール: `music_autoplay`（on/off切替）
- APIエンドポイント: `POST /api/player/autoplay`

### GuildVoiceState

```python
@dataclass
class GuildVoiceState:
    current_track: Optional[Track] = None
    start_time: Optional[datetime] = None
    idle_task: Optional[asyncio.Task] = None
    autoplay: bool = True              # オートプレイon/off
    played_urls: set = field(default_factory=set)  # 重複防止用
```

## 5. スラッシュコマンド

HalfMaid Bot が直接提供するDiscordスラッシュコマンド。

| コマンド | 説明 | 応答 |
|---|---|---|
| `/np` | 現在再生中の曲を表示 | Embed（タイトル、アーティスト、進行時間、サムネイル、リクエスター、音量/ループ/シャッフル/オートプレイ状態） |
| `/queue` | 再生キューを表示 | Embed（Now Playing + Up Next リスト最大10曲 + 状態） |
| `/skip` | 現在の曲をスキップ | テキスト「Skipped!」 |
| `/stop` | 再生停止＆VC退出 | テキスト「Stopped and disconnected.」 |

### Embed例（/np）

```
Now Playing
━━━━━━━━━━━━━━
曲名（リンク付き）
Artist: アーティスト名
Progress: 2:30 / 4:15
Requested by: ユーザー名
[サムネイル画像]

Vol: 50% | Autoplay: on
```

## 6. API エンドポイント

Rajitanの `music_player_api` ハンドラから呼ばれるHTTP API。

| メソッド | パス | 概要 |
|---|---|---|
| POST | `/api/player/play` | 再生 or キュー追加 |
| POST | `/api/player/stop` | 停止＆切断 |
| POST | `/api/player/pause` | 一時停止 / 再開 |
| POST | `/api/player/skip` | スキップ |
| POST | `/api/player/volume` | 音量変更（0-100） |
| POST | `/api/player/loop` | ループモード（off/track/queue） |
| POST | `/api/player/shuffle` | シャッフル切替 |
| POST | `/api/player/autoplay` | オートプレイon/off |

## 7. Rajitan側ツール定義（YAML）

`tools/music_player/` ディレクトリに9個のYAMLツール定義:

| ツール名 | 説明 |
|---|---|
| `music_play` | 音楽再生 / キュー追加 |
| `music_stop` | 停止＆退出 |
| `music_pause` | 一時停止 / 再開 |
| `music_skip` | スキップ |
| `music_queue` | キュー表示 |
| `music_volume` | 音量変更 |
| `music_now_playing` | 再生中の曲情報 |
| `music_search` | YouTube検索 |
| `music_autoplay` | オートプレイon/off |

すべて `builtin: music_player_api` ハンドラで、`_endpoint` + `_method` によりHalfMaid APIに転送される。

## 8. yt-dlp 検索仕様

### 通常検索（extract）
- `default_search: ytsearch10` — 最大10件取得
- entriesを順番に試行し、最初に有効なものを使用
- 日本語アーティスト名の検索精度向上

### 関連動画取得（get_related）
- `extract_flat: True` でメタデータのみ高速取得
- `related_videos` フィールドまたは `entries` から関連動画を抽出
- `exclude_urls` で再生済みURLを除外

### ストリームURL更新（refresh_stream_url）
- YouTube stream URLは数時間で失効する
- キューの次の曲を再生する前に毎回リフレッシュ

## 9. 依存関係

- `discord.py[voice]==2.6.4` — Discord Bot + Voice
- `yt-dlp` — YouTube検索・ストリームURL抽出
- `PyNaCl<1.6` — discord.py voice暗号化
- `ffmpeg` (system) — 音声デコード・エンコード
- `libopus` (system) — Opus音声コーデック（client.pyで明示的にロード）
- `FastAPI` + `uvicorn` — HTTP API

## 10. 環境変数

| 変数名 | 説明 |
|---|---|
| `HALFMAID_DISCORD_TOKEN` | HalfMaid Bot用Discordトークン |
| `HALFMAID_API_URL` | HalfMaid APIのURL（デフォルト: `http://localhost:8001`） |

## 11. 運用

```bash
# サービス管理
sudo systemctl start halfmaid
sudo systemctl stop halfmaid
sudo systemctl restart halfmaid
sudo systemctl status halfmaid

# ログ確認
sudo journalctl -u halfmaid -f

# デプロイ
cd ~/Rajitan-Discord && git pull
sudo systemctl restart halfmaid && sudo systemctl restart rajitan
```
