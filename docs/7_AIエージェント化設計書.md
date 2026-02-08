# Rajitan AIエージェント化 設計書

## Context

現在のRajitanは「インテント分類 → ハンドラ実行」の単発処理アーキテクチャ。ユーザーの1メッセージに対して1アクションしか実行できず、複数ステップの推論・計画・検証ができない。

本設計は、Claude Code・Manus・Devinのエージェント設計パターンを参考に、Rajitanをフルエージェントアーキテクチャに進化させる。

**目標:** ユーザーの意志を受け取り、計画→ツール実行→検証→ループで自律的にタスクを遂行するAIエージェント。

---

## 1. アーキテクチャ全体像

```
ユーザー（Discord メンション / スラッシュコマンド）
  ↓
RajitanBot (bot/client.py) — Discordイベントハンドリング
  ↓
AgentOrchestrator (agent/orchestrator.py) — エントリーポイント
  ↓
┌─→ LLMProvider.chat_completion(context + tool_definitions)
│    ↓
│   ツール呼び出し判定（function calling）
│    ↓
│   ToolRegistry.execute(tool_name, args)
│    ↓
│   結果をcontextにappend
│    ↓
│   完了判定 or ループ継続
└── 未完了なら繰り返し（MAX_STEPS制限）
  ↓
最終応答 → Discord送信
```

---

## 2. 新規ディレクトリ構造

```
rajitan/agent/                    # 新規パッケージ
├── __init__.py
├── orchestrator.py               # AgentOrchestrator — メインエージェントループ
├── llm/
│   ├── __init__.py
│   ├── base.py                   # LLMProvider ABC
│   └── openai_provider.py        # OpenAI実装（function calling対応）
├── tools/
│   ├── __init__.py
│   ├── base.py                   # Tool ABC, ToolResult, ToolRegistry
│   ├── summary_tool.py           # 会話要約
│   ├── quiz_tool.py              # クイズ生成・実行
│   ├── music_tool.py             # 音楽レコメンド
│   ├── schedule_tool.py          # スケジュール管理（CRUD）
│   ├── task_tool.py              # LeveMagi タスク管理
│   ├── conversation_tool.py      # 会話履歴取得・分析
│   ├── character_tool.py         # キャラクター設定変更
│   └── discord_tool.py           # Discordメッセージ送信・リアクション
└── memory/
    ├── __init__.py
    └── manager.py                # MemoryManager（短期・中期・長期）
```

---

## 3. コンポーネント詳細設計

### 3.1 Tool基盤 (`agent/tools/base.py`)

```python
class ToolResult:
    success: bool
    data: Any
    error: Optional[str]

class Tool(ABC):
    name: str                     # "summary", "quiz" 等
    description: str              # LLMに渡す説明文
    parameters: Dict              # JSON Schema（function calling用）

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult

class ToolRegistry:
    _tools: Dict[str, Tool]

    def register(self, tool: Tool)
    def get(self, name: str) -> Tool
    def get_function_definitions(self) -> List[Dict]  # OpenAI function calling用
    def list_tools(self) -> List[str]
```

**既存コード → Tool変換マッピング:**

| Tool名 | 既存コード | 主要メソッド |
|---|---|---|
| `summary` | `ConversationSummarizer` | `generate_summary()`, `format_summary_for_discord()` |
| `quiz` | `QuizGenerator` + `QuizRunner` | `generate_quiz()`, `start_quiz()` |
| `music` | `MusicRecommender` | `generate_recommendation()` |
| `schedule_create` | `EnhancedScheduleManager` | `add_schedule()` |
| `schedule_list` | `EnhancedScheduleManager` | `get_schedules()` |
| `schedule_delete` | `EnhancedScheduleManager` | `remove_schedule()` |
| `task_add` | `LeveMagiClient` | `create_leaf()` |
| `task_complete` | `LeveMagiClient` | `complete_leaf()` |
| `task_list` | `LeveMagiClient` | `get_user_leaves()` |
| `project_list` | `LeveMagiClient` | `get_user_nuts()` |
| `get_conversation` | `ConversationTracker` | `get_recent_conversation()` |
| `analyze_mood` | `ConversationAnalyzer` | `analyze_conversation_activity()` |
| `send_message` | Discord API | `channel.send()` |
| `add_reaction` | Discord API | `message.add_reaction()` |

計14ツール。100個以下の制約を大幅にクリア。

### 3.2 LLMプロバイダー抽象化 (`agent/llm/`)

```python
# base.py
class LLMProvider(ABC):
    @abstractmethod
    async def chat_completion(
        self,
        messages: List[Dict],
        tools: Optional[List[Dict]] = None,
        temperature: float = 0.7
    ) -> LLMResponse

class LLMResponse:
    content: Optional[str]            # テキスト応答
    tool_calls: Optional[List[ToolCall]]  # ツール呼び出し
    usage: Dict                        # トークン使用量

class ToolCall:
    name: str
    arguments: Dict

# openai_provider.py
class OpenAIProvider(LLMProvider):
    """既存のOpenAIClient.clientを再利用。function calling対応を追加"""
    def __init__(self, client: AsyncOpenAI, model: str = "gpt-4o-mini"):
        self.client = client  # 既存のAsyncOpenAIインスタンス
        self.model = model
```

**既存コード再利用:** `api/openai_client.py`の`AsyncOpenAI`インスタンスとモデル設定をそのまま使用。`chat.completions.create()`に`tools`パラメータを追加するだけ。

### 3.3 AgentOrchestrator (`agent/orchestrator.py`)

```python
class AgentOrchestrator:
    MAX_STEPS = 15

    def __init__(
        self,
        llm_provider: LLMProvider,
        tool_registry: ToolRegistry,
        memory_manager: MemoryManager,
        character_manager: CharacterManager
    )

    async def execute(
        self,
        user_message: str,
        context: AgentContext   # guild_id, channel_id, user_id, message等
    ) -> AgentResult:
        """メインエージェントループ"""
        # 1. システムプロンプト構築（不変プレフィックス + キャラクター + ツール説明）
        # 2. メモリから関連コンテキスト取得
        # 3. ステップループ開始
        #    - LLM呼び出し（messages + tools）
        #    - tool_callsがあれば実行、結果をappend
        #    - テキスト応答があれば完了
        #    - MAX_STEPS到達で強制終了
        # 4. エピソードをメモリに記録

class AgentContext:
    guild_id: str
    channel_id: str
    user_id: str
    username: str
    message: discord.Message          # Discord message object（ツールが使う）
    conversation_history: List[Dict]  # append-only

class AgentResult:
    response: str                     # ユーザーへの最終応答
    success: bool
    steps_taken: int
    tools_used: List[str]
```

**エージェントループの原則（ユーザーのリファレンスに準拠）:**
- コンテキストはappend-only（前のアクション/結果を書き換えない）
- エラー履歴もコンテキストに残す
- ツール定義は起動時に全ロード、動的追加・削除しない
- システムプロンプトのプレフィックスは不変

### 3.4 メモリアーキテクチャ (`agent/memory/manager.py`)

```python
class MemoryManager:
    def __init__(self, redis_client, db_client):
        self.redis = redis_client    # 既存RedisClient再利用
        self.db = db_client          # 既存SQLiteClient再利用

    # --- 短期記憶（現在のエージェント実行中）---
    # → AgentOrchestrator内のconversation_historyリストで管理
    # → 外部保存不要。実行完了時にエピソードとして中期に移行

    # --- 中期記憶（直近の対話エピソード）---
    async def save_episode(self, guild_id, channel_id, user_id,
                           user_request, steps, result, timestamp)
    async def get_recent_episodes(self, channel_id, limit=10) -> List[Episode]

    # --- 長期記憶（永続化されたナレッジ）---
    async def save_user_preference(self, user_id, key, value)
    async def get_user_preferences(self, user_id) -> Dict
    async def save_guild_knowledge(self, guild_id, key, value)

    # --- コンテキスト構築 ---
    async def build_context(self, guild_id, channel_id, user_id) -> str
        """メモリ各層から関連情報を集めてプロンプト用テキストを構築"""
```

**ストレージマッピング:**
- 短期 → Python list（AgentOrchestrator内、揮発性）
- 中期 → Redis（既存`redis_client.set_cache/get_cache`再利用、メモリフォールバック付き）
- 長期 → SQLite（新テーブル: `agent_episodes`, `user_preferences`, `guild_knowledge`）

### 3.5 システムプロンプト設計

```
[不変プレフィックス]
あなたは「{character_name}」という名前のAIアシスタントです。
Discordサーバー「{guild_name}」で活動しています。

[キャラクター設定]
{personality_prompt}  ← 既存character/prompts.pyから

[利用可能なツール]
以下のツールを使って、ユーザーのリクエストに応えてください。
複数のツールを組み合わせて、段階的にタスクを完了できます。
ツールの実行結果を確認してから、次のアクションを決定してください。

[メモリコンテキスト]
{memory_context}  ← MemoryManager.build_context()から

[現在の会話]
{recent_messages}  ← ConversationTracker.get_recent_conversation()から
```

### 3.6 Discord統合 (`bot/client.py` 変更)

**変更箇所:** `handle_mention()` と `process_mention_with_nlp()` をAgentOrchestrator呼び出しに置き換え

```python
# 現在: handle_mention → process_mention_with_nlp → IntentRouter.route()
# 変更後: handle_mention → agent_orchestrator.execute()

async def handle_mention(self, message):
    content = self._extract_mention_content(message)
    context = AgentContext(
        guild_id=str(message.guild.id),
        channel_id=str(message.channel.id),
        user_id=str(message.author.id),
        username=message.author.display_name,
        message=message
    )

    async with message.channel.typing():  # タイピングインジケーター
        result = await self.agent_orchestrator.execute(content, context)

    if result.response:
        await message.channel.send(result.response)
```

**スラッシュコマンドも統合:** `bot/commands.py`の各コマンドハンドラから`agent_orchestrator.execute()`を呼ぶ。コマンド名をそのままユーザーメッセージとして渡す（例: `/summary` → `"会話を要約して"`）。

### 3.7 main.py 変更

`RajitanApplication.initialize()`に以下を追加:

```python
# エージェントシステム初期化
from rajitan.agent.orchestrator import AgentOrchestrator
from rajitan.agent.llm.openai_provider import OpenAIProvider
from rajitan.agent.tools.base import ToolRegistry
from rajitan.agent.tools import (summary_tool, quiz_tool, music_tool, ...)
from rajitan.agent.memory.manager import MemoryManager

llm_provider = OpenAIProvider(self.openai_client.client, self.openai_client.model)
tool_registry = ToolRegistry()
# 全ツールを起動時に一括登録
tool_registry.register(SummaryTool(self.conversation_summarizer, self.conversation_tracker))
tool_registry.register(QuizTool(self.quiz_generator, self.quiz_runner))
# ... 全14ツール登録

memory_manager = MemoryManager(self.redis_client, self.db_client)
agent_orchestrator = AgentOrchestrator(llm_provider, tool_registry, memory_manager, self.character_manager)

# 既存のinject_dependenciesに追加
bot.inject_dependencies(agent_orchestrator=agent_orchestrator, ...)
```

---

## 4. 将来のサブエージェント設計（Phase 3以降）

Phase 1-2完了後、メインエージェントの能力を分割する形で導入:

```
AgentOrchestrator (メイン)
├── MusicSpecialist     — 音楽検索・レコメンド・将来的にVoice再生
├── ScheduleSpecialist  — スケジュール解析・CRUD・cron管理
├── TaskSpecialist      — LeveMagi連携・プロジェクト管理
└── KnowledgeSpecialist — 会話分析・要約・ナレッジ蓄積
```

各サブエージェントは:
- 自身のツールサブセットを持つ
- 独立したコンテキストで動作（メインのコンテキスト汚染を防ぐ）
- メインエージェントがLLMの判断で委譲する

---

## 5. 実装フェーズ

### Phase 1: Tool基盤 + エージェントループ
1. `agent/tools/base.py` — Tool ABC, ToolResult, ToolRegistry
2. `agent/llm/base.py` + `openai_provider.py` — LLMプロバイダー抽象化
3. 既存機能をToolとしてラップ（14ツール）
4. `agent/orchestrator.py` — メインエージェントループ
5. `bot/client.py` — handle_mentionをOrchestrator経由に変更
6. `main.py` — エージェントシステムの初期化追加

### Phase 2: メモリ階層
1. `agent/memory/manager.py` — MemoryManager
2. SQLiteに新テーブル追加（agent_episodes, user_preferences, guild_knowledge）
3. エピソード記録・検索
4. コンテキスト構築にメモリ統合

### Phase 3: サブエージェント
1. サブエージェント基底クラス
2. MusicSpecialist, ScheduleSpecialist等の実装
3. メインエージェントからの委譲ロジック
4. コンテキスト分離

### Phase 4: 高度な機能
1. 能動的介入（会話の盛り上がり検知 → 自発的に提案）
2. 学習（ユーザー行動パターンの記録・活用）
3. 音楽プレーヤー機能（Voice Channel連携）

---

## 6. 変更対象ファイル一覧

| ファイル | 変更種別 | 内容 |
|---|---|---|
| `rajitan/agent/` (新規パッケージ全体) | **新規** | エージェントコア |
| `rajitan/bot/client.py` | **修正** | handle_mention → Orchestrator呼び出し |
| `rajitan/bot/commands.py` | **修正** | スラッシュコマンド → Orchestrator経由 |
| `rajitan/main.py` | **修正** | エージェントシステム初期化追加 |
| `rajitan/storage/sqlite_client.py` | **修正** | 新テーブル追加（Phase 2） |
| `rajitan/nlp/intent_classifier.py` | 廃止予定 | エージェントのLLM判断に置き換え |
| `rajitan/nlp/intent_strategy.py` | 廃止予定 | ツールシステムに置き換え |

**再利用するファイル（変更なし）:**
- `rajitan/api/openai_client.py` — AsyncOpenAIインスタンスを再利用
- `rajitan/conversation/` — 全ファイルそのまま（Toolからラップ）
- `rajitan/features/` — 全ファイルそのまま（Toolからラップ）
- `rajitan/scheduler/` — そのまま（Toolからラップ）
- `rajitan/storage/` — RedisClient, LeveMagiClientそのまま
- `rajitan/character/` — そのまま（プロンプト構築に使用）
- `rajitan/utils/` — decorators, validators, logger, configそのまま

---

## 7. 検証方法

### Phase 1完了時の検証
1. メンションで単純な会話ができる（GeneralChat相当）
2. 「要約して」→ summaryツールが呼ばれて要約が返る
3. 「クイズ出して」→ quizツールが呼ばれる
4. 「今日の19時に要約して」→ schedule_createツールでスケジュール作成
5. 複合リクエスト「要約してからクイズ出して」→ 2ツール連続実行
6. 既存テスト `pytest rajitan/tests/ -v` が通る

### Phase 2完了時の検証
1. 同じユーザーが再度話しかけた時、前回の文脈を覚えている
2. 「さっきの続き」のような曖昧な指示に対応できる
3. エピソードログがSQLiteに記録されている
