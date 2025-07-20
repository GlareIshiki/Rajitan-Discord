import discord
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any
from rajitan.scheduler.schedule_models import ScheduleSummary, FunctionType, ExecutionPattern
from rajitan.utils.logger import get_logger

logger = get_logger("schedule_visualizer")


class ScheduleVisualizer:
    """Handles visualization of schedules in Discord"""
    
    def __init__(self):
        pass
    
    def create_schedule_list_embed(
        self, 
        schedules: List[ScheduleSummary], 
        channel_name: Optional[str] = None,
        guild_name: Optional[str] = None
    ) -> discord.Embed:
        """Create an embed showing schedule list"""
        
        if channel_name:
            title = f"📅 {channel_name} のスケジュール一覧"
        elif guild_name:
            title = f"📅 {guild_name} のスケジュール一覧"
        else:
            title = "📅 スケジュール一覧"
        
        embed = discord.Embed(
            title=title,
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        if not schedules:
            embed.description = "設定されたスケジュールはありません。"
            embed.add_field(
                name="💡 ヒント",
                value="メンション（@らじたん）で「19:00に音楽をおすすめして」のように話しかけると、スケジュールを設定できます！",
                inline=False
            )
            return embed
        
        # Group schedules by status
        active_schedules = [s for s in schedules if s.is_active]
        inactive_schedules = [s for s in schedules if not s.is_active]
        
        # Active schedules
        if active_schedules:
            active_text = ""
            for schedule in active_schedules[:10]:  # Limit to 10 for readability
                function_emoji = self._get_function_emoji(schedule.function_type)
                pattern_text = self._format_pattern_text(schedule.pattern)
                status_text = self._get_status_text(schedule)
                next_run = self._format_next_execution(schedule.next_execution)
                
                active_text += f"{function_emoji} **{self._get_function_name(schedule.function_type)}**\n"
                active_text += f"   📋 {pattern_text}\n"
                active_text += f"   ⏰ 次回実行: {next_run}\n"
                active_text += f"   📊 {status_text}\n\n"
            
            if len(active_schedules) > 10:
                active_text += f"... その他 {len(active_schedules) - 10} 件のスケジュール\n"
            
            embed.add_field(
                name="🟢 アクティブなスケジュール",
                value=active_text or "なし",
                inline=False
            )
        
        # Inactive schedules
        if inactive_schedules:
            inactive_text = ""
            for schedule in inactive_schedules[:5]:  # Limit to 5 for inactive
                function_emoji = self._get_function_emoji(schedule.function_type)
                pattern_text = self._format_pattern_text(schedule.pattern)
                
                inactive_text += f"{function_emoji} {self._get_function_name(schedule.function_type)} - {pattern_text}\n"
            
            if len(inactive_schedules) > 5:
                inactive_text += f"... その他 {len(inactive_schedules) - 5} 件\n"
            
            embed.add_field(
                name="🔴 停止中のスケジュール",
                value=inactive_text or "なし",
                inline=False
            )
        
        # Summary statistics
        total_executions = sum(s.execution_count for s in schedules)
        failed_schedules = len([s for s in schedules if s.consecutive_failures > 0])
        
        embed.add_field(
            name="📊 統計情報",
            value=f"総スケジュール数: {len(schedules)}\n"
                  f"総実行回数: {total_executions}\n"
                  f"エラーのあるスケジュール: {failed_schedules}",
            inline=True
        )
        
        embed.set_footer(text="スケジュールの設定・変更は @らじたん にメンションして話しかけてください")
        
        return embed
    
    def create_schedule_detail_embed(self, schedule: ScheduleSummary) -> discord.Embed:
        """Create detailed embed for a single schedule"""
        function_emoji = self._get_function_emoji(schedule.function_type)
        function_name = self._get_function_name(schedule.function_type)
        
        embed = discord.Embed(
            title=f"{function_emoji} スケジュール詳細: {function_name}",
            color=discord.Color.green() if schedule.is_active else discord.Color.red(),
            timestamp=datetime.now()
        )
        
        # Basic info
        embed.add_field(
            name="📋 基本情報",
            value=f"**ID**: {schedule.id}\n"
                  f"**機能**: {function_name}\n"
                  f"**パターン**: {self._format_pattern_text(schedule.pattern)}\n"
                  f"**状態**: {'🟢 アクティブ' if schedule.is_active else '🔴 停止中'}",
            inline=True
        )
        
        # Execution info
        next_run = self._format_next_execution(schedule.next_execution)
        last_run = self._format_last_execution(schedule.last_executed)
        
        embed.add_field(
            name="⏰ 実行情報",
            value=f"**次回実行**: {next_run}\n"
                  f"**前回実行**: {last_run}\n"
                  f"**実行回数**: {schedule.execution_count}回",
            inline=True
        )
        
        # Status and health
        health_status = self._get_health_status(schedule)
        embed.add_field(
            name="🏥 健康状態",
            value=health_status,
            inline=True
        )
        
        # Creation info
        created_date = schedule.created_at.strftime("%Y/%m/%d %H:%M")
        embed.add_field(
            name="👤 作成情報",
            value=f"**作成者**: <@{schedule.created_by}>\n"
                  f"**作成日時**: {created_date}",
            inline=False
        )
        
        embed.set_footer(text=f"Schedule ID: {schedule.id}")
        
        return embed
    
    def create_execution_history_embed(
        self, 
        schedule: ScheduleSummary, 
        executions: List[Dict[str, Any]]
    ) -> discord.Embed:
        """Create embed showing execution history"""
        function_emoji = self._get_function_emoji(schedule.function_type)
        function_name = self._get_function_name(schedule.function_type)
        
        embed = discord.Embed(
            title=f"📊 実行履歴: {function_emoji} {function_name}",
            color=discord.Color.blue(),
            timestamp=datetime.now()
        )
        
        if not executions:
            embed.description = "実行履歴はありません。"
            return embed
        
        # Recent executions
        history_text = ""
        for execution in executions[:10]:  # Show last 10 executions
            status_emoji = "✅" if execution.get("success", False) else "❌"
            exec_time = execution.get("executed_at", datetime.now())
            if isinstance(exec_time, str):
                exec_time = datetime.fromisoformat(exec_time)
            
            time_str = exec_time.strftime("%m/%d %H:%M")
            duration = execution.get("execution_time_ms", 0)
            duration_str = f" ({duration}ms)" if duration else ""
            
            history_text += f"{status_emoji} {time_str}{duration_str}\n"
            
            if not execution.get("success", False) and execution.get("error_message"):
                error_msg = execution["error_message"][:50] + "..." if len(execution["error_message"]) > 50 else execution["error_message"]
                history_text += f"   💥 {error_msg}\n"
        
        embed.add_field(
            name="📝 最近の実行履歴",
            value=history_text or "履歴なし",
            inline=False
        )
        
        # Statistics
        total_executions = len(executions)
        successful_executions = len([e for e in executions if e.get("success", False)])
        success_rate = (successful_executions / total_executions * 100) if total_executions > 0 else 0
        
        avg_duration = 0
        duration_executions = [e for e in executions if e.get("execution_time_ms")]
        if duration_executions:
            avg_duration = sum(e["execution_time_ms"] for e in duration_executions) / len(duration_executions)
        
        embed.add_field(
            name="📈 統計",
            value=f"**総実行回数**: {total_executions}\n"
                  f"**成功率**: {success_rate:.1f}%\n"
                  f"**平均実行時間**: {avg_duration:.0f}ms",
            inline=True
        )
        
        embed.set_footer(text=f"Schedule ID: {schedule.id}")
        
        return embed
    
    def _get_function_emoji(self, function_type: FunctionType) -> str:
        """Get emoji for function type"""
        emoji_map = {
            FunctionType.SUMMARY: "📝",
            FunctionType.QUIZ: "🧩",
            FunctionType.MUSIC: "🎵",
            FunctionType.CUSTOM_MESSAGE: "💬"
        }
        return emoji_map.get(function_type, "⚙️")
    
    def _get_function_name(self, function_type: FunctionType) -> str:
        """Get Japanese name for function type"""
        name_map = {
            FunctionType.SUMMARY: "会話要約",
            FunctionType.QUIZ: "クイズ出題",
            FunctionType.MUSIC: "音楽推薦",
            FunctionType.CUSTOM_MESSAGE: "カスタムメッセージ"
        }
        return name_map.get(function_type, "不明な機能")
    
    def _format_pattern_text(self, pattern: ExecutionPattern) -> str:
        """Format execution pattern for display"""
        pattern_map = {
            ExecutionPattern.ONCE: "一回限り",
            ExecutionPattern.HOURLY: "毎時実行",
            ExecutionPattern.DAILY: "毎日実行",
            ExecutionPattern.WEEKLY: "毎週実行",
            ExecutionPattern.MONTHLY: "毎月実行"
        }
        return pattern_map.get(pattern, "不明なパターン")
    
    def _get_status_text(self, schedule: ScheduleSummary) -> str:
        """Get status text for schedule"""
        if not schedule.is_active:
            return "🔴 停止中"
        
        if schedule.consecutive_failures > 0:
            return f"⚠️ 連続失敗 {schedule.consecutive_failures}回"
        
        if schedule.execution_count == 0:
            return "🆕 未実行"
        
        return "✅ 正常"
    
    def _format_next_execution(self, next_execution: Optional[datetime]) -> str:
        """Format next execution time"""
        if not next_execution:
            return "未設定"
        
        now = datetime.now()
        
        # If it's in the past, show as overdue
        if next_execution < now:
            return "⚠️ 実行待ち"
        
        # Calculate time difference
        diff = next_execution - now
        
        if diff.days > 0:
            return f"{next_execution.strftime('%m/%d %H:%M')} ({diff.days}日後)"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{next_execution.strftime('%H:%M')} ({hours}時間後)"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{next_execution.strftime('%H:%M')} ({minutes}分後)"
        else:
            return "まもなく"
    
    def _format_last_execution(self, last_execution: Optional[datetime]) -> str:
        """Format last execution time"""
        if not last_execution:
            return "未実行"
        
        now = datetime.now()
        diff = now - last_execution
        
        if diff.days > 0:
            return f"{last_execution.strftime('%m/%d %H:%M')} ({diff.days}日前)"
        elif diff.seconds > 3600:
            hours = diff.seconds // 3600
            return f"{last_execution.strftime('%H:%M')} ({hours}時間前)"
        elif diff.seconds > 60:
            minutes = diff.seconds // 60
            return f"{last_execution.strftime('%H:%M')} ({minutes}分前)"
        else:
            return "先ほど"
    
    def _get_health_status(self, schedule: ScheduleSummary) -> str:
        """Get health status text"""
        if not schedule.is_active:
            return "🔴 停止中"
        
        if schedule.consecutive_failures >= 3:
            return "💀 重篤（連続失敗多数）"
        elif schedule.consecutive_failures >= 2:
            return "⚠️ 注意（連続失敗）"
        elif schedule.consecutive_failures >= 1:
            return "🟡 軽微な問題"
        elif schedule.execution_count == 0:
            return "🆕 新規作成"
        else:
            return "🟢 健全"