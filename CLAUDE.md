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
source venv/bin/activate      # Linux / macOS
# venv\Scripts\activate       # Windows
pip install -r requirements.txt
cp .env.example .env          # 必須: DISCORD_BOT_TOKEN, OPENAI_API_KEY

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
Bot + FastAPI は `asyncio.gather()` で並行起動。シグナル（SIGINT/SIGTERM）で逆順にグレースフルシャットダウン。

```
RajitanApplication (main.py)
  ├── SQLiteClient, RedisClient
  ├── OpenAIClient, YouTubeClient, SpotifyClient
  ├── CharacterManager, ConversationTracker/Analyzer/Summarizer
  ├── QuizGenerator/Runner, MusicRecommender
  ├── EnhancedScheduleManager, TriggerManager
  ├── LeveMagiClient
  ├── AgentOrchestrator ← LLMProvider + ToolRegistry(15tools) + 既存サービス
  └── RajitanBot ← inject_dependencies() で全サービス注入
```

```
rajitan/
├── agent/         # AIエージェントシステム（Phase 1実装済み）
│   ├── orchestrator.py  # エージェントループ（MAX_STEPS=15、append-onlyコンテキスト）
│   ├── llm/       # LLMプロバイダー抽象化（base.py: ABC, openai_provider.py: function calling）
│   ├── tools/     # ツールシステム（base.py: Tool ABC/ToolRegistry, 各種ツール実装）
│   └── memory/    # メモリ管理（Phase 2で実装予定）
├── bot/           # Discord bot本体（client.py, commands.py, levemagi_commands.py）
├── character/     # AIキャラクター管理・性格・プロンプト
├── conversation/  # 会話トラッキング・分析・要約
├── features/      # クイズ(quiz/)・音楽レコメンド(music/)・LeveMagi通知
├── api/           # OpenAI・Spotify・YouTube クライアント
├── storage/       # SQLite・Redis・Pydanticモデル・LeveMagi CRUD
├── scheduler/     # EnhancedScheduleManager・TriggerManager
├── nlp/           # レガシー: インテント分類（エージェント未使用時のフォールバック）
├── web/           # FastAPI サーバー・認証・APIルート
├── utils/         # ログ・設定(config.py)・バリデーション・デコレータ
└── tests/         # pytest テスト（conftest.pyにモックfixtures）
```

## Key Patterns

### Agent System (Primary — Phase 1実装済み)
メンション時の処理フロー: `on_message` → `_handle_mention_with_agent()` → `AgentOrchestrator.execute()` → LLM + Tool Loop

```
AgentOrchestrator (agent/orchestrator.py)
  ├── LLMProvider.chat_completion(messages + tool_definitions)
  ├── ToolRegistry.execute(tool_name, args)  # 15ツール登録済み
  ├── append-onlyコンテキスト（エラー履歴も保持）
  └── MAX_STEPS=15 で強制終了
```

**登録ツール一覧（15個）:**
| Tool | 既存サービス | 機能 |
|---|---|---|
| `summary` | ConversationSummarizer | 会話要約 |
| `quiz` | QuizGenerator/Runner | クイズ生成・実行 |
| `music` | MusicRecommender | 音楽レコメンド |
| `schedule_create/list/delete` | EnhancedScheduleManager | スケジュールCRUD |
| `task_add/complete/list` | LeveMagiClient | タスク管理 |
| `project_list` | LeveMagiClient | プロジェクト一覧 |
| `get_conversation` | ConversationTracker | 会話履歴取得 |
| `analyze_mood` | ConversationAnalyzer | 雰囲気分析 |
| `character` | CharacterManager | 性格変更 |
| `send_message` / `add_reaction` | Discord API | メッセージ送信・リアクション |

- 新しいツールを追加: `Tool` ABCを継承 → `main.py` で `ToolRegistry.register()` → LLMが自動認識
- ツール定義は起動時に全ロード、動的追加・削除しない

### Intent Routing (Legacy Fallback)
`agent_orchestrator`がNoneの場合のみ使用。`IntentClassifier` → `IntentRouter` → `IntentHandler`

### Decorators (Cross-cutting Concerns)
```python
@handle_async_errors(operation_name="...", default_return=..., reraise=...)
@with_retries(max_retries=2, delay=1.0)
```

## Key Files

- `rajitan/main.py` — エントリーポイント。ProcessManager（PIDファイルで重複起動防止）+ RajitanApplication（ライフサイクル管理）+ エージェントシステム初期化
- `rajitan/bot/client.py` — RajitanBot。メンション → `_handle_mention_with_agent()` → AgentOrchestrator（フォールバック: legacy NLP）
- `rajitan/bot/commands.py` — スラッシュコマンド（/setup, /personality, /chat, /summary, /quiz, /music, /schedules, /status, /help）
- `rajitan/agent/orchestrator.py` — AgentOrchestrator。メインエージェントループ（plan → tool → verify → loop）
- `rajitan/agent/llm/base.py` — LLMProvider ABC、LLMResponse、ToolCallデータクラス
- `rajitan/agent/llm/openai_provider.py` — OpenAI function calling実装。既存AsyncOpenAIインスタンスを再利用
- `rajitan/agent/tools/base.py` — Tool ABC、ToolResult、ToolRegistry（全ツール管理）
- `rajitan/scheduler/enhanced_manager.py` — スケジュール実行（DB永続化、cron風パターン、60秒ポーリング）
- `rajitan/utils/config.py` — .envからの設定読み込み（70+項目）
- `rajitan/utils/decorators.py` — `@handle_async_errors`, `@with_retries`
- `rajitan/utils/validators.py` — 入力バリデーション一元管理（Discord ID, プロンプト長, インターバル範囲等）

## Web API (FastAPI)

`API_ENABLED=true` で起動。RajitanWebUI（Next.js）からアクセスされる。
`app_state` dictにサービス参照を格納し、ルートハンドラから `app_state.get("key")` でアクセス。

- `rajitan/web/server.py` — FastAPIアプリ作成、CORS、サービスstate注入
- `rajitan/web/auth.py` — Discord OAuth認証（Redisセッション）
- `rajitan/web/routes/bot.py` — `/api/bot/stats`, `/api/bot/guilds`, `/api/bot/activity`, `/api/bot/stats/users`
- `rajitan/web/routes/levemagi.py` — `/api/levemagi/*` LeveMagi CRUD（Nuts/Leaves/Trunks/Roots/Portals/Resources/Tags/User/Gacha）
- `rajitan/web/routes/calendar.py` — カレンダー関連

## Storage

**SQLite** (`storage/sqlite_client.py`): guilds, channels, characters, schedules, schedule_executions, usage_stats, LeveMagiテーブル群
**Redis** (`storage/redis_client.py`): 会話データ、セッション、実行履歴。未接続時はメモリ辞書にフォールバック
**LeveMagi** (`storage/levemagi_client.py`): lm_users, lm_nuts, lm_leaves, lm_trunks, lm_roots, lm_portals, lm_resources, lm_tags, lm_worklogs

## Environment Variables

必須: `DISCORD_BOT_TOKEN`, `OPENAI_API_KEY`
任意: `YOUTUBE_API_KEY`, `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET` (なくてもYouTube検索URLで動作)
任意: `REDIS_HOST`/`REDIS_PORT` (なければメモリフォールバック)
API: `API_ENABLED=true`, `API_HOST`, `API_PORT=8000`, `API_CORS_ORIGINS`

## Key Decisions

- 全体が**async/await**設計（aiosqlite, AsyncOpenAI, discord.py async）
- イベントハンドラは `client.py` に直接実装（Cog分離はしない）
- `SchedulerManager`（基本版）は削除済み。`EnhancedScheduleManager` が唯一のスケジューラ
- 音楽レコメンドはAPIキーなしでもYouTube検索URLで動作
- 会話データはRedis/メモリに保存するが、不足時はDiscord API履歴にフォールバック
- 入力バリデーションは `utils/validators.py` で一元管理
- パーソナリティ7種: default, cheerful, calm, witty, professional, friendly, sarcastic

## Deployment

- **Rajitan-Discord** → XServer VPS `85.131.243.117`（Bot + FastAPI常時起動、systemd管理）
- **RajitanWebUI** → Vercel（GitHub連携で自動デプロイ）
- **API URL**: `https://api.glareishiki.com` → nginx (HTTPS:443) → FastAPI (localhost:8000)
- **SSL**: Let's Encrypt (certbot自動更新)
- **nginx設定**: `/etc/nginx/sites-available/rajitan-api`

### VPS運用コマンド（systemd）

```bash
# サービス管理
sudo systemctl start rajitan       # 起動
sudo systemctl stop rajitan        # 停止
sudo systemctl restart rajitan     # 再起動
sudo systemctl status rajitan      # 状態確認

# ログ確認
sudo journalctl -u rajitan -f                    # リアルタイム
sudo journalctl -u rajitan --since "1 hour ago"  # 直近1時間

# コード更新 → 反映
cd ~/Rajitan-Discord && git pull && sudo systemctl restart rajitan
```

- サービス定義: `/etc/systemd/system/rajitan.service`（ソース: `rajitan.service`）
- クラッシュ時は10秒後に自動再起動
- VPS再起動時も自動起動（enabled）

## 関連リポジトリ

- **RajitanWebUI** — Next.js 15 フロントエンド。本リポジトリのFastAPI APIを消費する
