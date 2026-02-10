"""
Workflow configuration dataclasses.

Each dataclass mirrors a section of workflows/default.yaml.
All fields have defaults matching the original hardcoded values,
so the bot works identically even without a YAML file.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class StepParams:
    max_tokens: int = 1500
    tools_enabled: bool = True


@dataclass
class AgentLoopConfig:
    max_steps: int = 15
    temperature: float = 0.7
    step_params_normal: StepParams = field(default_factory=lambda: StepParams(1500, True))
    step_params_near_end: StepParams = field(default_factory=lambda: StepParams(800, True))
    step_params_final: StepParams = field(default_factory=lambda: StepParams(800, False))
    reflection_interval: int = 3
    urgency_threshold: int = 3


@dataclass
class ComplexityConfig:
    min_length: int = 10
    light_patterns: List[str] = field(default_factory=lambda: [
        "こんにちは", "おはよう", "おやすみ", "こんばんは",
        "やっほ", "やあ", "よお", "ちーす", "ちーっす", "おっす",
        "ただいま", "おかえり", "ひさしぶり",
        "ありがとう", "サンキュー", "了解", "おけ", "おっけ",
        "ひま", "暇", "元気", "調子", "なにしてる",
        "面白い", "うける", "わろた", "草",
        "好き", "かわいい", "すごい",
    ])


@dataclass
class ContextConfig:
    warning_threshold: int = 80_000
    keep_last_n_exchanges: int = 4
    chars_per_token: int = 3
    summary_keep_entries: int = 6


@dataclass
class ResponseGateConfig:
    timeout_seconds: float = 10.0
    max_tokens: int = 5
    temperature: float = 0.0
    thinking: bool = False
    failsafe_send: bool = True
    failsafe_participate: str = "skip"
    gate_prompt: str = ""
    participate_prompt: str = ""


@dataclass
class StepInjectionConfig:
    first_step: str = (
        "【ステップ 1/{max_steps}】まず計画を立ててください。"
        "何のツールを使うか、何ステップ必要か考えてから実行してください。"
    )
    normal: str = "【ステップ {step}/{max_steps}、残り{remaining}】"
    reflection: str = (
        "元のリクエスト：「{original_request}」\n"
        "進捗確認: 目的は達成できた？同じツールを繰り返していない？"
        "達成できたなら最終回答へ。"
    )
    urgency: str = (
        "残りステップが少ないです。達成できていれば最終回答を。"
        "未達成なら最も重要なアクション1つに絞ってください。"
    )
    final_step: str = (
        "【システム】これが最後のステップです。"
        "ツールを使わず、今までの結果をもとに最終回答してください。"
    )


@dataclass
class PromptsConfig:
    identity: str = "あなたはDiscordサーバーで活動するAIアシスタント「らじたん」です。"
    thinking_protocol: str = ""
    tool_usage_guide: str = ""
    error_recovery_guide: str = ""
    response_format_guide: str = ""
    memory_usage_guide: str = ""
    step_injection: StepInjectionConfig = field(default_factory=StepInjectionConfig)
    messages: Dict[str, str] = field(default_factory=lambda: {
        "llm_failure": "ごめん、うまく考えられなかった...もう一度試してみて！",
        "max_steps_exceeded": "ごめん、処理が複雑すぎてうまくいかなかった。もう少しシンプルに伝えてくれると助かる！",
        "verification_nudge": "\n（確認: この結果は期待通りか？目的達成なら最終回答へ）",
        "consecutive_tool_warning": (
            "\n\n【注意】{tool_name}を{count}回連続で使用中。"
            "本当に繰り返す必要がありますか？目的達成なら最終回答に進んでください。"
        ),
        "double_failure_warning": (
            "\n\n【注意】このツールは2回連続で失敗しました。"
            "別のアプローチを試すか、ユーザーに状況を説明してください。"
        ),
    })


@dataclass
class ToolOverride:
    max_calls_per_execution: int = 5


@dataclass
class ToolsConfig:
    default_max_calls: int = 5
    overrides: Dict[str, ToolOverride] = field(default_factory=dict)
    disabled: List[str] = field(default_factory=list)


@dataclass
class TeamConfig:
    """Multi-agent team configuration."""
    enabled: bool = False
    max_sub_agents: int = 3
    sub_agent_max_steps: int = 8
    sub_agent_timeout_seconds: float = 60.0
    sub_agent_temperature: float = 0.7
    sub_agent_max_tokens: int = 1500
    decompose_max_tokens: int = 800
    decompose_temperature: float = 0.3
    synthesize_max_tokens: int = 1500
    synthesize_temperature: float = 0.7
    min_message_length: int = 30


@dataclass
class AgentTeamsConfig:
    """Agent Teams: role-based collaborative multi-agent system."""
    enabled: bool = False
    max_teammates: int = 4
    max_tasks: int = 8
    teammate_max_steps: int = 8
    teammate_timeout_seconds: float = 90.0
    overall_timeout_seconds: float = 180.0
    teammate_temperature: float = 0.7
    teammate_max_tokens: int = 1500
    plan_max_tokens: int = 1200
    plan_temperature: float = 0.3
    synthesize_max_tokens: int = 2000
    synthesize_temperature: float = 0.7
    min_message_length: int = 40
    max_waves: int = 4


@dataclass
class WorkflowConfig:
    """Complete workflow configuration (base + user overlay merged)."""
    version: int = 1
    name: str = "default"
    description: str = ""
    agent_loop: AgentLoopConfig = field(default_factory=AgentLoopConfig)
    complexity: ComplexityConfig = field(default_factory=ComplexityConfig)
    context: ContextConfig = field(default_factory=ContextConfig)
    response_gate: ResponseGateConfig = field(default_factory=ResponseGateConfig)
    prompts: PromptsConfig = field(default_factory=PromptsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    team: TeamConfig = field(default_factory=TeamConfig)
    agent_teams: AgentTeamsConfig = field(default_factory=AgentTeamsConfig)
