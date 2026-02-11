# persona/

## 目的
ペルソナ（パーソナリティ切替）の全ビジネスロジック。DB・キャッシュ・Discord identity更新を統合。

## 主要ファイル
- `manager.py` — `PersonaManager`: resolve/CRUD/キャッシュ。DI: `db_client`, `character_manager`
- `identity.py` — `update_bot_identity()`: Discord nickname + avatar更新。純粋関数

## 実行フロー
```
PersonaManager.resolve_persona(guild_id)
  1. db_client.persona.get_guild_active_persona_id()  ← characters.active_persona_id
  2. character_manager.get_character() → personality_traits.type → preset
  3. fallback: preset_default
```

## 依存関係
- `storage/persona_repo.py` — DB操作（PersonaManager → db_client.persona.*）
- `storage/persona_models.py` — Pydanticモデル（Persona, PersonaCreate, PersonaUpdate）
- `character/manager.py` — レガシーfallback用（personality_traits.type → preset解決）
- `agent/tools/character_tool.py` — CharacterTool（services: persona_manager, bot）
- `web/routes/personas.py` — WebUI API

## 注意事項
- `_persona_cache` はインメモリ。set/update/delete時にinvalidate
- avatar更新はDiscord APIレート制限あり（`update_bot_identity` で handled）
