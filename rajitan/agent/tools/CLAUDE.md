# agent/tools/

## 目的
YAMLドリブンのツールシステム。36個のツール定義（`tools/` ディレクトリのYAML）を読み込み、統一的に実行する。

## 主要ファイル
- `base.py` — `Tool` ABC, `ToolResult`, `ToolRegistry`（YAML専用、per-execution呼び出し制限）
- `definition.py` — `ToolDefinition`（YAMLパース）, `ToolDefinitionLoader`（全YAML走査）
- `executor.py` — `GenericExecutor`（4ハンドラーへのルーティング）
- `service_registry.py` — `ServiceRegistry`（文字列名→サービスインスタンスのDI）
- `*_tool.py` — `python_class`ハンドラー用のレガシーToolクラス群

## 4つのハンドラータイプ
| ハンドラー | 用途 | YAML設定 |
|---|---|---|
| `builtin` | 組み込みロジック（time, web_search, music_player_api） | `_builtin_name` |
| `discord_action` | Discord API操作（send_message, add_reaction） | `_action` |
| `service_method` | ServiceRegistryのメソッド呼び出し | `_service`, `_method` |
| `python_class` | 既存Toolクラスの再利用 | `module`, `class`, `services` |

## 依存関係
- YAML定義: `<project_root>/tools/<category>/<name>.yaml`
- サービス注入: `main.py` で `ServiceRegistry.register()` → `GenericExecutor` に渡す
- ワークフロー連携: `workflow/schema.py` の `ToolsConfig` でツール有効/無効を制御

## 注意事項
- `ToolResult.data` にはデータのみ。ユーザー向け文言はエージェントが生成する
- 新ツール追加はYAMLファイルの作成のみ（`python_class`以外はPythonコード不要）
