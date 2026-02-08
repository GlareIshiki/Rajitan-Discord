# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AIラジオDJ風Discordボット。会話を追跡し、要約・クイズ・音楽レコメンドを能動的に提供する。
FastAPIでWebダッシュボード（RajitanWebUI）向けのAPIも提供。

## Tech Stack

- Python 3.11/3.12（3.13非対応: audioop削除のため）
- discord.py 2.3.2
- OpenAI API (gpt-4o-mini) via AsyncOpenAI
- FastAPI + uvicorn（Web API）
- Redis（任意、メモリフォールバックあり）
- SQLite (aiosqlite)

## Commands

```bash
# セットアップ
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env   # 必須: DISCORD_BOT_TOKEN, OPENAI_API_KEY

# 起動
python -m rajitan.main

# テスト
pip install -r requirements-dev.txt
pytest rajitan/tests/ -v
pytest rajitan/tests/test_validators.py -v  # 単体テスト実行
pytest rajitan/tests/ -v -k "test_name"     # 特定テスト実行
```

## Architecture

DIパターン。`main.py` の `RajitanApplication` が全サービスを初期化し、`RajitanBot` に注入する。

```
RajitanApplication (main.py)
  ├── SQLiteClient, RedisClient
  ├── OpenAIClient, YouTubeClient, SpotifyClient
  ├── CharacterManager, ConversationTracker/Analyzer/Summarizer
  ├── QuizGenerator/Runner, MusicRecommender
  ├── EnhancedScheduleManager, TriggerManager
  ├── LeveMagiClient
  └── RajitanBot ← inject_dependencies() で全サービス注入
```

```
rajitan/
├── bot/           # Discord bot本体（client.py, commands.py, levemagi_commands.py）
├── character/     # AIキャラクター管理・性格・プロンプト
├── conversation/  # 会話トラッキング・分析・要約
├── features/      # クイズ(quiz/)・音楽レコメンド(music/)・LeveMagi通知
├── api/           # OpenAI・Spotify・YouTube クライアント
├── storage/       # SQLite・Redis・Pydanticモデル・LeveMagi CRUD
├── scheduler/     # EnhancedScheduleManager・TriggerManager
├── nlp/           # インテント分類・ルーティング・スケジュールパース
├── web/           # FastAPI サーバー・認証・APIルート
├── utils/         # ログ・設定(config.py)・バリデーション・デコレータ
└── tests/         # pytest テスト（conftest.pyにモックfixtures）
```

## Key Files

- `rajitan/main.py` — エントリーポイント。ProcessManager（PIDファイルで重複起動防止）+ RajitanApplication（ライフサイクル管理）
- `rajitan/bot/client.py` — RajitanBot。イベントハンドラ、メンション処理、`get_bot_stats()`/`get_user_breakdown()`
- `rajitan/bot/commands.py` — スラッシュコマンド（/setup, /personality, /chat, /summary, /quiz, /music, /schedules, /status, /help）
- `rajitan/nlp/intent_strategy.py` — メンション時のインテントルーティング（Strategy パターン）
- `rajitan/scheduler/enhanced_manager.py` — スケジュール実行（DB永続化、cron風パターン）
- `rajitan/utils/config.py` — .envからの設定読み込み（70+項目）
- `rajitan/utils/decorators.py` — `@handle_async_errors`, `@with_retries`

## Web API (FastAPI)

`API_ENABLED=true` で起動。RajitanWebUI（Next.js）からアクセスされる。

- `rajitan/web/server.py` — FastAPIアプリ作成、CORS、サービスstate注入
- `rajitan/web/auth.py` — Discord OAuth認証
- `rajitan/web/routes/bot.py` — `/api/bot/stats`, `/api/bot/guilds`, `/api/bot/activity`, `/api/bot/stats/users`
- `rajitan/web/routes/levemagi.py` — `/api/levemagi/*` LeveMagi CRUD（Nuts/Leaves/Trunks/Roots/Portals/Resources/Tags/User/Gacha）
- `rajitan/web/routes/calendar.py` — カレンダー関連

## Storage

**SQLite** (`storage/sqlite_client.py`): guilds, channels, characters, schedules, usage_stats, LeveMagiテーブル群
**Redis** (`storage/redis_client.py`): 会話データ、セッション、実行履歴。未接続時はメモリ辞書にフォールバック
**LeveMagi** (`storage/levemagi_client.py`): lm_users, lm_nuts, lm_leaves, lm_trunks, lm_roots, lm_portals, lm_resources, lm_tags, lm_worklogs

## Key Decisions

- 全体が**async/await**設計（aiosqlite, AsyncOpenAI, discord.py async）
- イベントハンドラは `client.py` に直接実装（Cog分離はしない）
- `SchedulerManager`（基本版）は削除済み。`EnhancedScheduleManager` が唯一のスケジューラ
- 音楽レコメンドはAPIキーなしでもYouTube検索URLで動作
- 会話データはRedis/メモリに保存するが、不足時はDiscord API履歴にフォールバック
- 入力バリデーションは `utils/validators.py` で一元管理

## 関連リポジトリ

- **RajitanWebUI** (`../RajitanWebUI/`) — Next.js 15 フロントエンド。本リポジトリのFastAPI APIを消費する
