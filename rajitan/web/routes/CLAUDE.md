# web/routes/

## 目的
FastAPI APIルート。RajitanWebUI (Next.js) から呼ばれるREST API群。

## 主要ファイル
- `bot.py` — Bot状態・ギルド一覧・統計・ギルド設定
- `personas.py` — ペルソナCRUD + アバターアップロード/削除 + アクティブ切替
- `tools.py` — YAMLツール定義の一覧・詳細・YAML取得 (WebUI用)
- `levemagi.py` — LeveMagi CRUD (Portal/Nuts/Trunk/Leaf/Root)
- `workflow.py` — ワークフロー設定の取得・更新
- `calendar.py` — Google Calendar連携
- `instagram_auth.py` / `canva_auth.py` / `google_auth.py` — 各種OAuth認証フロー

## パターン
- サービスアクセス: `from rajitan.web.server import app_state` → `app_state.get("service_name")`
- 認証: `auth.py` の `get_current_user()` → Discord OAuthトークン検証
- レスポンス: snake_case（WebUI側 `api.ts` で自動camelCase変換）

## 依存関係
- `server.py` — FastAppの作成、CORS設定、StaticFilesマウント、`app_state` dict定義
- `auth.py` — Discord OAuth検証、Redis/メモリでセッション管理
- サービス群は `main.py` で `app_state` に注入される
