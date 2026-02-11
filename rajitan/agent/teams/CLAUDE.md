# agent/teams/

## 目的
役割の異なる専門エージェントが依存関係付きタスクを協調実行するAgent Teamsシステム。

## 主要ファイル
- `team_coordinator.py` — `AgentTeamCoordinator`: エントリーポイント。should_use_team()判定 + 全体オーケストレーション
- `leader.py` — `TeamLeader`: plan()でタスク分解 → synthesize()で結果統合
- `teammate.py` — `TeammateRunner`: 個別タスク実行（エージェントループのミニ版、max_steps=8）
- `task_graph.py` — `TaskGraph`: Kahn'sアルゴリズムでWave分割、依存関係の検証
- `mailbox.py` — `TeamMailbox`: エージェント間メッセージング
- `models.py` — `TeamRole`, `TeamTask`, `TeamMessage`, `TeamResult`

## 実行フロー
```
Leader.plan() → TaskGraph(Kahn's) → Wave実行 → Leader.synthesize()
  Wave内: 同一ロール=順次、異ロール=並列（asyncio.gather）
```

## 依存関係
- `workflows/default.yaml` の `agent_teams:` セクションで有効/無効を制御
- `orchestrator.py` の3段階判定: Agent Teams → Sub-Agent(`team/`) → 単一エージェント
- チームツール（`team_report`, `team_message`）はToolRegistry外、インライン処理

## 注意事項
- 全LLMコールは **non-thinking** (DeepSeekのcontent空問題回避)
- `send_message`/`add_reaction`はTeammateから除外（Leaderのみ最終送信）
