# Rajitan-Discord

AIラジオDJ風のDiscordボット。会話の要約、クイズ、音楽レコメンドを通じてサーバーの会話を盛り上げる。

## 機能

### スラッシュコマンド
| コマンド | 説明 |
|---|---|
| `/setup` | キャラクターの初期設定（名前・パーソナリティ） |
| `/personality` | ドロップダウンでパーソナリティ変更 + カスタムプロンプト設定 |
| `/chat` | プライベートチャット（自分だけに見える） |
| `/summary` | 会話の要約を生成 |
| `/quiz` | 会話ベースのクイズを開始 |
| `/music` | 会話の雰囲気に合った音楽をおすすめ |
| `/schedules` | スケジュール一覧の表示 |
| `/status` | ボットのステータス表示 |
| `/help` | ヘルプ情報 |

### メンション機能
- `@らじたん こんにちは` - 通常チャット
- `@らじたん 要約して` - 会話を要約
- `@らじたん クイズ出して` - クイズを開始
- `@らじたん 音楽おすすめして` - 音楽を推薦
- `@らじたん 19:00に要約して` - スケジュール設定（確認付き）

### パーソナリティ
7種類: default, cheerful, calm, witty, professional, friendly, sarcastic

## セットアップ

### 必要環境
- Python 3.11 or 3.12（3.13非対応）
- Discord Bot Token
- OpenAI API Key

### インストール

```bash
git clone https://github.com/GlareIshiki/Rajitan-Discord.git
cd Rajitan-Discord
python -m venv venv
# Windows
venv\Scripts\activate
# Linux / macOS
source venv/bin/activate

pip install -r requirements.txt
```

### 環境変数（.env）

```env
# 必須
DISCORD_BOT_TOKEN=your_discord_bot_token
OPENAI_API_KEY=your_openai_api_key

# 任意（音楽機能強化）
YOUTUBE_API_KEY=your_youtube_api_key
SPOTIFY_CLIENT_ID=your_spotify_client_id
SPOTIFY_CLIENT_SECRET=your_spotify_client_secret

# 任意（Redis未設定ならメモリフォールバック）
REDIS_HOST=localhost
REDIS_PORT=6379

# その他
DATABASE_URL=sqlite:///rajitan.db
DEBUG=True
LOG_LEVEL=INFO
```

### 起動

```bash
python -m rajitan.main
```

### APIキーについて

| API | 必須 | 用途 |
|---|---|---|
| Discord Bot Token | 必須 | Bot接続 |
| OpenAI API Key | 必須 | 応答生成・要約・クイズ・音楽レコメンド |
| YouTube Data API | 任意 | 音楽のYouTubeリンク取得 |
| Spotify Web API | 任意 | 音楽のSpotifyリンク取得 |

YouTube/Spotify APIキーがない場合でも、音楽レコメンド機能はYouTube検索リンクとして動作します。

## テスト

```bash
pip install -r requirements-dev.txt
pytest rajitan/tests/ -v
```
