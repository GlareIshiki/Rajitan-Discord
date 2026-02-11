# tools/ (YAML定義ディレクトリ)

## 目的
36個のツール定義YAML。AI・WebUI・実行ランタイムの全情報を1ファイルに集約。

## YAML構造
```yaml
version: 1
meta:       # WebUI表示用 (display_name, category, icon, tags)
ai:         # LLM向け (name, description, parameters, hints)
execution:  # ランタイム (handler, module/class/services, max_calls_per_execution)
```

## カテゴリ (12)
character(1), conversation(4), discord(2), integration(4), media(2), memory(2),
music_player(10), quiz(2), schedule(3), task(4), utility(2), workflow(1)

## 新ツール追加手順
1. `tools/<category>/<name>.yaml` を作成
2. handler=`service_method`/`builtin` ならPythonコード不要
3. handler=`python_class` なら `rajitan/agent/tools/` にクラス追加
4. `main.py` でサービス登録が必要な場合は `ServiceRegistry.register()` 追加

## 読み込み
`ToolDefinitionLoader` (`rajitan/agent/tools/definition.py`) が起動時に全走査。動的な追加・削除はしない。
