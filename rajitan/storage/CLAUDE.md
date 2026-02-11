# storage/

## 目的
永続化層。SQLite + Redis。リポジトリパターンでドメイン別にDB操作を分離。

## 主要ファイル
- `sqlite_client.py` — `SQLiteClient`: メインDBクライアント。DDL + guild/character/schedule/workflow/model_settings操作
- `persona_repo.py` — `PersonaRepo`: personas テーブル専用。`SQLiteClient.persona` 経由
- `agent_memory_repo.py` — `AgentMemoryRepo`: agent_memories テーブル専用。`SQLiteClient.memory` 経由
- `redis_client.py` — `RedisClient`: 会話・セッション・メモリ。未接続時はメモリfallback
- `models.py` — SQLiteデータモデル（Guild, Channel, Character, Schedule等）
- `persona_models.py` — Pydanticモデル（Persona, PersonaCreate, PersonaUpdate）
- `levemagi_client.py` — LeveMagi専用DBクライアント

## アクセスパターン
```python
db_client = SQLiteClient()
db_client.persona.get_persona(id)       # PersonaRepo
db_client.memory.upsert(...)            # AgentMemoryRepo
db_client.get_character(guild_id)       # 直接メソッド
```

## 注意事項
- VPSのSQLiteバージョンが古いため、UNIQUE制約に式（COALESCE等）を使わない
- 新しいドメインのDB操作はリポジトリとして分離し、`SQLiteClient.xxx` でアクセスする
