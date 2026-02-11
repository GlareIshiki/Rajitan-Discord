# halfmaid/

## 目的
音楽再生用の別Botプロセス「HalfMaid」。Rajitanとは独立して動作する。

## 主要ファイル
- `main.py` — エントリーポイント。Bot + FastAPI並行起動
- `bot/client.py` — `HalfMaidBot` (discord.py)
- `bot/voice.py` — `VoiceManager` (FFmpeg + PyNaCl)
- `queue/manager.py` — `QueueManager` (再生キュー管理)
- `api/server.py` — FastAPI (localhost:8001)
- `storage/database.py` — `PlaylistDatabase` (halfmaid.db, SQLite)
- `config.py` — 環境変数 (`HALFMAID_DISCORD_TOKEN`, `HALFMAID_API_URL`)

## 通信
Rajitan → HalfMaid: HTTP API (localhost:8001)
- Rajitanの `music_player_api` builtinハンドラーがAPI転送
- YAML定義: `tools/music_player/*.yaml` の `_endpoint` + `_method`

## 依存
yt-dlp (ストリームURL抽出), FFmpeg (音声変換), PyNaCl (Opus暗号化)

## systemd
`halfmaid.service` — 別プロセスとして独立起動。Rajitan再起動とは独立。
