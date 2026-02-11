# agent/memory/

## 目的
3層記憶アーキテクチャ。エージェントの文脈理解を支える。

## 主要ファイル
- `manager.py` — `MemoryManager`: 3層の読み書き統合。`has_pending_action()` は毎メッセージ呼ばれる高速パス
- `writer.py` — `AgentMemoryWriter`: `execute()`完了後に自動書き込み。ツール名→待ちアクションの自動マッピング
- `prompt_integrator.py` — `MemoryPromptIntegrator`: 記憶→システムプロンプト変換。予算~700トークン(2100文字)
- `models.py` — データクラス群

## 3層構造
| 層 | ストレージ | TTL | 用途 |
|---|---|---|---|
| Tier 1 | メモリdict + Redis | 1時間 | ワーキングメモリ（クイズ回答待ち等） |
| Tier 2 | Redis | 6時間 | アクションログ（要約した、タスク追加した等） |
| Tier 3 | SQLite (agent_memories) | 永続 | ユーザーの好み、チャンネルの特徴 |

## 依存関係
- `storage/redis_client.py`, `storage/sqlite_client.py`（Redis未接続時はメモリフォールバック）
- `agent/prompts.py` が `MemoryPromptIntegrator` を呼ぶ
- `agent/orchestrator.py` が `AgentMemoryWriter` を呼ぶ

## プロンプト注入の優先度
Tier 1（常に全量）→ Tier 2（直近5件）→ Tier 3（残り予算で最大5件）
