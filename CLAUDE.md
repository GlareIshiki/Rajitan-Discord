# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AIラジオDJ風Discordボット「らじたん」。会話を追跡し、要約・クイズ・音楽レコメンドを能動的に提供する。
DeepSeek v3による自律エージェントシステムを搭載。FastAPIでWebダッシュボード（RajitanWebUI）向けのAPIも提供。

## Tech Stack

- Python 3.11/3.12（3.13非対応: audioop削除のため）
- discord.py 2.3.2
- DeepSeek v3 (deepseek-chat) — エージェントの頭脳（function calling）
- OpenAI API (gpt-4o-mini) — レガシー機能（要約・クイズ・音楽・感情分析）
- FastAPI + uvicorn（Web API）
- Redis（任意、メモリフォールバックあり）
- SQLite (aiosqlite)

## Commands

```bash
# セットアップ
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # 必須: DISCORD_BOT_TOKEN, DEEPSEEK_API_KEY

# 起動
python -m rajitan.main

# テスト
pip install -r requirements-dev.txt
python -m pytest rajitan/tests/ -v
python -m pytest rajitan/tests/test_validators.py -v  # 単体テスト
python -m pytest rajitan/tests/ -v -k "test_name"     # 特定テスト
```

## Architecture

DIパターン。`main.py` の `RajitanApplication` が全サービスを初期化し、`RajitanBot` に注入する。
Bot + FastAPI は `asyncio.gather()` で並行起動。シグナル（SIGINT/SIGTERM）で逆順にグレースフルシャットダウン。

### Dual-LLM構成

```
DeepSeek v3 (deepseek-chat)          OpenAI (gpt-4o-mini)
  ↓                                     ↓
AgentOrchestrator                    OpenAIClient
  └── 思考・計画・ツール実行            └── 要約・クイズ・音楽・感情分析
```

`DEEPSEEK_API_KEY` 設定時はエージェントがDeepSeekを使用。未設定時はOpenAIにフォールバック。

### 初期化ツリー

```
RajitanApplication (main.py)
  ├── SQLiteClient, RedisClient
  ├── OpenAIClient (gpt-4o-mini), YouTubeClient, SpotifyClient
  ├── CharacterManager, ConversationTracker/Analyzer/Summarizer
  ├── QuizGenerator/Runner, MusicRecommender
  ├── EnhancedScheduleManager, TriggerManager
  ├── LeveMagiClient
  ├── AgentOrchestrator ← DeepSeek/OpenAI + ToolRegistry(15tools) + 既存サービス
  └── RajitanBot ← inject_dependencies() で全サービス注入
```

### ディレクトリ構造

```
rajitan/
├── agent/         # AIエージェントシステム
│   ├── orchestrator.py     # エージェントループ（MAX_STEPS=15）
│   ├── prompts.py          # 思考プロトコル付きシステムプロンプト構築
│   ├── context_manager.py  # コンテキストウィンドウ管理（トークン概算・圧縮）
│   ├── llm/       # LLMプロバイダー抽象化（DeepSeek/OpenAI共通）
│   ├── tools/     # ツールシステム（base.py: Tool ABC/ToolRegistry, 15ツール）
│   └── memory/    # メモリ管理（Phase 2で実装予定）
├── bot/           # Discord bot本体（client.py, commands.py, levemagi_commands.py）
├── character/     # AIキャラクター管理・性格・プロンプト（8種: default〜rajitan）
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

## Agent System

### 処理フロー

`on_message` → `_handle_mention_with_agent()` → `AgentOrchestrator.execute()` → LLM + Tool Loop

### 思考プロトコル（prompts.py）

LLMに構造化された思考プロセスを指示:
1. 【理解】ユーザーのリクエストを把握
2. 【判断】ツールが必要か判断
3. 【計画】複数ステップなら実行順序を決定
4. 【実行】ツール呼び出し
5. 【確認】結果がユーザーの目的を達成したか検証
6. 【応答】自然な言葉でユーザーに伝える

### エージェントループの仕組み（orchestrator.py）

- **append-onlyコンテキスト**: メッセージ履歴は追加のみ、エラー履歴も保持
- **適応的max_tokens**: 通常1500 → 終盤800 → 最終ステップはツール無効化しテキスト応答を強制
- **目標追跡**: 4ステップごとにユーザーの元のリクエストをリマインダーとして注入
- **エラー回復**: 同一ツール2回連続失敗で回復ヒントを注入
- **コンテキスト管理**: 80Kトークン超過で古い交換を圧縮（context_manager.py）

### 登録ツール（15個）

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

## Key Patterns

### Decorators (Cross-cutting Concerns)
```python
@handle_async_errors(operation_name="...", default_return=..., reraise=...)
@with_retries(max_retries=2, delay=1.0)
```

## Key Files

- `rajitan/main.py` — エントリーポイント。ProcessManager + RajitanApplication + エージェント初期化（DeepSeek/OpenAI分岐）
- `rajitan/bot/client.py` — RajitanBot。メンション → `_handle_mention_with_agent()` → AgentOrchestrator
- `rajitan/agent/orchestrator.py` — エージェントループ。思考→ツール→検証→応答
- `rajitan/agent/prompts.py` — AgentPromptBuilder。思考プロトコル・エラー対応・応答ルールを含むシステムプロンプト構築
- `rajitan/agent/context_manager.py` — ContextManager。トークン概算（日本語3文字≈1トークン）・コンテキスト圧縮
- `rajitan/agent/llm/openai_provider.py` — OpenAI互換API実装（DeepSeek/OpenAI共用）
- `rajitan/agent/tools/base.py` — Tool ABC、ToolResult、ToolRegistry
- `rajitan/utils/config.py` — .envからの設定読み込み
- `rajitan/utils/validators.py` — 入力バリデーション一元管理

## Web API (FastAPI)

`API_ENABLED=true` で起動。RajitanWebUI（Next.js）からアクセスされる。
`app_state` dictにサービス参照を格納し、ルートハンドラから `app_state.get("key")` でアクセス。

- `rajitan/web/server.py` — FastAPIアプリ作成、CORS、サービスstate注入
- `rajitan/web/auth.py` — Discord OAuth認証（Redisセッション）
- `rajitan/web/routes/bot.py` — `/api/bot/stats`, `/api/bot/guilds`, `/api/bot/activity`, `/api/bot/stats/users`
- `rajitan/web/routes/levemagi.py` — `/api/levemagi/*` LeveMagi CRUD
- `rajitan/web/routes/calendar.py` — カレンダー関連

## Storage

**SQLite** (`storage/sqlite_client.py`): guilds, channels, characters, schedules, schedule_executions, usage_stats, LeveMagiテーブル群
**Redis** (`storage/redis_client.py`): 会話データ、セッション、実行履歴。未接続時はメモリ辞書にフォールバック
**LeveMagi** (`storage/levemagi_client.py`): lm_users, lm_nuts, lm_leaves, lm_trunks, lm_roots, lm_portals, lm_resources, lm_tags, lm_worklogs

## Environment Variables

必須: `DISCORD_BOT_TOKEN`
LLM: `DEEPSEEK_API_KEY`（エージェント用）, `OPENAI_API_KEY`（レガシー機能用）
任意: `YOUTUBE_API_KEY`, `SPOTIFY_CLIENT_ID`/`SPOTIFY_CLIENT_SECRET`
任意: `REDIS_HOST`/`REDIS_PORT` (なければメモリフォールバック)
API: `API_ENABLED=true`, `API_HOST`, `API_PORT=8000`, `API_CORS_ORIGINS`

## Key Decisions

- 全体が**async/await**設計（aiosqlite, AsyncOpenAI, discord.py async）
- エージェントはDeepSeek v3主軸、OpenAIは既存機能で継続使用（Dual-LLM）
- イベントハンドラは `client.py` に直接実装（Cog分離はしない）
- `EnhancedScheduleManager` が唯一のスケジューラ
- 会話データはRedis/メモリに保存、不足時はDiscord API履歴にフォールバック
- パーソナリティ8種: default, cheerful, calm, witty, professional, friendly, sarcastic, rajitan

## Deployment

- **Rajitan-Discord** → XServer VPS `85.131.243.117`（Bot + FastAPI常時起動、systemd管理）
- **RajitanWebUI** → Vercel（GitHub連携で自動デプロイ）
- **API URL**: `https://api.glareishiki.com` → nginx (HTTPS:443) → FastAPI (localhost:8000)
- **SSL**: Let's Encrypt (certbot自動更新)

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
- クラッシュ時は10秒後に自動再起動、VPS再起動時も自動起動

## 関連リポジトリ

- **RajitanWebUI** — Next.js 15 フロントエンド。本リポジトリのFastAPI APIを消費する
