# character/

## 目的
キャラクター（ギルドごとの名前・システムプロンプト・パーソナリティタイプ）の管理。
ペルソナ関連ロジックは `persona/` パッケージに分離済み。

## 主要ファイル
- `manager.py` — `CharacterManager`: キャラクターCRUD、レスポンス生成、パーソナリティ管理
- `personality.py` — `PersonalityManager`: 8種のプリセットtrait定義、スタイル計算
- `prompts.py` — システムプロンプトテンプレート、`DEFAULT_SYSTEM_PROMPT`

## 依存関係
- `storage/sqlite_client.py` — characters テーブル（create_character, get_character）
- `persona/manager.py` — ペルソナ解決時にlegacy fallbackとして `get_character()` を参照
- `api/openai_client.py` — レスポンス生成（レガシー）
