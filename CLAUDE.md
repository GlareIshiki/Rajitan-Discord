# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

AIラジオDJ風Discordボット「らじたん」。会話を追跡し、要約・クイズ・音楽レコメンドを能動的に提供する。
DeepSeek v3による自律エージェントシステムを搭載。FastAPIでWebダッシュボード（RajitanWebUI）向けのAPIも提供。

## Tech Stack

- Python 3.11/3.12（3.13非対応: audioop削除のため）
- discord.py 2.3.2
- DeepSeek v3 (deepseek-chat) — エージェントの頭脳（function calling + thinking mode）
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

### DeepSeek Thinking Mode

- **エージェント推論には有効**: `orchestrator.py`で`_looks_complex()`がTrueのとき`thinking=True`
- **分類タスクには不向き**: YES/SKIP/LEAVE判定でcontent空になる問題
- `thinking=True` + `temperature=0` + `max_tokens`小 → contentが空、reasoning_contentのみ返る
- **結論**: 分類・判定タスク（ResponseGate等）は必ず`thinking=False`で呼ぶ

### 初期化ツリー

```
RajitanApplication (main.py)
  ├── SQLiteClient, RedisClient
  ├── OpenAIClient (gpt-4o-mini), YouTubeClient, SpotifyClient
  ├── CharacterManager, ConversationTracker/Analyzer/Summarizer
  ├── QuizGenerator/Runner, MusicRecommender
  ├── EnhancedScheduleManager, TriggerManager
  ├── LeveMagiClient
  ├── MemoryManager (3層記憶: Redis + SQLite)
  ├── AgentOrchestrator ← DeepSeek/OpenAI + ToolRegistry(22tools) + MemoryManager
  ├── ResponseGate ← LLM品質ゲート + 会話参加判定
  └── RajitanBot ← inject_dependencies() で全サービス注入
```

## Agent System

### 処理フロー

```
on_message
  ├── (pending_action あり) → メンション不要でエージェント起動
  ├── (メンション検出)     → handle_mention → エージェント起動
  └── (会話ウィンドウ内)   → ResponseGate.should_participate → yes/skip/leave
      ↓
_handle_mention_with_agent()
      ↓
AgentOrchestrator.execute()
  ├── _looks_complex() → thinking mode判定
  ├── システムプロンプト構築（キャラ + 思考プロトコル + 記憶 + 会話履歴）
  ├── LLM呼び出し → ツール実行 → 結果追記（append-only）
  ├── build_step_injection(): 3ステップごとに反省 + 残ステップ警告
  ├── MAX_STEPS(15)到達 or 最終テキスト応答 → ループ終了
  └── AgentMemoryWriter → 3層記憶に自動書き込み
      ↓
ResponseGate.should_send() → LLM品質チェック後に送信
```

### ResponseGate（応答品質ゲート + 会話参加判定）

`rajitan/agent/response_gate.py` — DeepSeekを**non-thinking**で呼び出し。

- `should_send(response, user_message)`: 応答品質チェック。内部思考の漏れ・重複を検出しブロック。フェイルセーフ=送信
- `should_participate(new_message, recent_messages)`: 会話ウィンドウ内での三択判定 YES/SKIP/LEAVE。フェイルセーフ=skip
- **会話ウィンドウ**: @メンション後2分間（`CONVERSATION_WINDOW_SECONDS=120`）、メンションなしで応答可能。LEAVEでウィンドウ即時終了

### エージェントループの仕組み（orchestrator.py）

- **append-onlyコンテキスト**: メッセージ履歴は追加のみ、エラー履歴も保持
- **適応的thinking mode**: `_looks_complex()` — 短文/挨拶パターンはnon-thinking、それ以外はthinking
- **適応的max_tokens**: 通常1500 → 終盤800 → 最終ステップはツール無効化しテキスト応答を強制
- **目標追跡**: 3ステップごとに反省プロンプト注入、残り3ステップ以下で緊急警告
- **エラー回復**: 同一ツール2回連続失敗で回復ヒント注入
- **ループ防止**: 同一ツール連続使用を検出して警告
- **コンテキスト管理**: 80Kトークン超過で古い交換を圧縮（context_manager.py、日本語3文字≈1トークン）

### 登録ツール（22個）

| Tool | 既存サービス | 機能 |
|---|---|---|
| `summary` | ConversationSummarizer | 会話要約 |
| `quiz` | QuizGenerator/Runner | クイズ生成・実行 |
| `quiz_answer` | QuizRunner + MemoryManager | クイズ回答処理・採点 |
| `music` | MusicRecommender | 音楽レコメンド |
| `schedule_create/list/delete` | EnhancedScheduleManager | スケジュールCRUD |
| `task_add/complete/list` | LeveMagiClient | タスク管理 |
| `project_list` | LeveMagiClient | プロジェクト一覧 |
| `get_conversation` | ConversationTracker | 会話履歴取得 |
| `search_conversation` | SQLite直接 | 会話検索 |
| `get_user_messages` | SQLite直接 | ユーザー発言取得 |
| `analyze_mood` | ConversationAnalyzer | 雰囲気分析 |
| `character` | CharacterManager | 性格変更 |
| `send_message` / `add_reaction` | Discord API | メッセージ送信・リアクション |
| `remember` / `recall` | MemoryManager | 長期記憶の読み書き |
| `get_current_time` | — | 現在日時・曜日取得 |
| `web_search` | Brave Search API | ウェブ検索（最大2回/実行） |

新しいツールを追加する手順: `Tool` ABCを継承 → `main.py` で `ToolRegistry.register()` → LLMが自動認識。
ツール定義は起動時に全ロード、動的追加・削除しない。

## 3層記憶システム（agent/memory/）

エージェントの文脈理解を支える記憶アーキテクチャ。

```
┌─ Tier 1: ワーキングメモリ（短期）─────────────────┐
│  メモリdict + Redis (TTL: 1時間)                   │
│  例: クイズ回答待ち、確認待ち、コンテキストメモ     │
├─ Tier 2: アクションログ（中期）───────────────────┤
│  Redis (TTL: 6時間)                                │
│  例: 要約した、クイズ出した、タスク追加した          │
├─ Tier 3: 永続記憶（長期）─────────────────────────┤
│  SQLite (agent_memories テーブル)                   │
│  例: ユーザーの好み、チャンネルの特徴               │
└───────────────────────────────────────────────────┘
    読み込み: MemoryPromptIntegrator → システムプロンプトに注入
    書き込み: AgentMemoryWriter → execute()完了後に自動 + ツール内
```

### メモリベースルーティング

`on_message` で毎回 `has_pending_action(channel_id)` を確認。待ちアクション（クイズ回答待ち等）がある場合、**メンションなしでもエージェントが起動**する。これにより「クイズ出題→回答」のような自然なマルチターン対話が可能。

### 記憶のプロンプト注入（prompt_integrator.py）

トークン予算: ~700トークン（2100文字）。優先度: Tier 1（常に全量）→ Tier 2（直近5件）→ Tier 3（残り予算で最大5件）。

## Key Patterns

### Decorators (Cross-cutting Concerns)
```python
@handle_async_errors(operation_name="...", default_return=..., reraise=...)
@with_retries(max_retries=2, delay=1.0)
```

### デュアルストレージ（Redis + メモリフォールバック）

RedisClient未接続時はメモリ辞書にフォールバック。QuizRunner, MemoryManagerが同パターン。
`has_pending_action()` は高速パス（メモリdict → Redis）で毎メッセージ呼ばれても問題ない。

### Intent Routing (Legacy Fallback)

`agent_orchestrator`がNoneの場合のみ使用。`IntentClassifier` → `IntentRouter` → `IntentHandler`

## Key Files

- `rajitan/main.py` — エントリーポイント。全サービス初期化、DeepSeek/OpenAI分岐、ツール登録
- `rajitan/bot/client.py` — RajitanBot。メンション/メモリベース/会話ウィンドウルーティング → AgentOrchestrator
- `rajitan/agent/orchestrator.py` — エージェントループ（MAX_STEPS=15、thinking mode適応切替）
- `rajitan/agent/response_gate.py` — LLM品質ゲート（should_send）+ 会話参加判定（should_participate）
- `rajitan/agent/prompts.py` — システムプロンプト構築（キャラ + 思考プロトコル + 記憶 + 会話）
- `rajitan/agent/memory/manager.py` — MemoryManager（3層記憶の読み書き統合）
- `rajitan/agent/memory/writer.py` — AgentMemoryWriter（execute後の自動書き込み、ツール→待ちアクションマッピング）
- `rajitan/agent/memory/prompt_integrator.py` — 記憶→システムプロンプト変換
- `rajitan/agent/tools/base.py` — Tool ABC、ToolResult、ToolRegistry（per-execution呼び出し制限付き）
- `rajitan/agent/llm/openai_provider.py` — OpenAI互換API実装（DeepSeek/OpenAI共用）
- `rajitan/agent/context_manager.py` — コンテキストウィンドウ管理（80Kトークン超で圧縮）
- `rajitan/utils/config.py` — .envからの設定読み込み

## Web API (FastAPI)

`API_ENABLED=true` で起動。RajitanWebUI（Next.js）からアクセスされる。
`app_state` dictにサービス参照を格納し、ルートハンドラから `app_state.get("key")` でアクセス。

## Storage

- **SQLite** (`storage/sqlite_client.py`): guilds, channels, characters, schedules, usage_stats, agent_memories, LeveMagiテーブル群
- **Redis** (`storage/redis_client.py`): 会話データ、セッション、ワーキングメモリ、アクションログ。未接続時はメモリ辞書にフォールバック
- **注意**: VPSのSQLiteバージョンが古いため、UNIQUE制約に式（COALESCE等）を使わないこと。カラムをNOT NULL DEFAULT ''にして単純なカラム参照で対応する

## Environment Variables

必須: `DISCORD_BOT_TOKEN`
LLM: `DEEPSEEK_API_KEY`（エージェント用）, `OPENAI_API_KEY`（レガシー機能用）
検索: `BRAVE_SEARCH_API_KEY`（web_searchツール用、任意）
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
- 分類・判定タスクは必ず`thinking=False`で呼ぶ（DeepSeek thinking modeの制約）

## Deployment

- **Rajitan-Discord** → XServer VPS（Bot + FastAPI常時起動、systemd管理）
- **RajitanWebUI** → Vercel（GitHub連携で自動デプロイ）
- **API URL**: `https://api.glareishiki.com` → nginx (HTTPS:443) → FastAPI (localhost:8000)

### VPS運用コマンド（systemd）

```bash
# サービス管理
sudo systemctl start rajitan
sudo systemctl stop rajitan
sudo systemctl restart rajitan
sudo systemctl status rajitan

# ログ確認
sudo journalctl -u rajitan -f                    # リアルタイム
sudo journalctl -u rajitan --since "1 hour ago"  # 直近1時間

# コード更新 → 反映
cd ~/Rajitan-Discord && git pull && sudo systemctl restart rajitan
```

サービス定義: `/etc/systemd/system/rajitan.service`。クラッシュ時は10秒後に自動再起動。

## 関連リポジトリ

- **RajitanWebUI** — Next.js 15 フロントエンド。本リポジトリのFastAPI APIを消費する
