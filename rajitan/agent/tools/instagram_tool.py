"""Instagram posting, image generation (Nanobanana), and Canva design tools."""

import io
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.instagram")


class InstagramPostTool(Tool):
    """Instagram写真投稿ツール"""

    name = "instagram_post"
    max_calls_per_execution = 2
    description = (
        "ユーザーのInstagramに画像を投稿する。画像URLとキャプションを指定する。"
        "ユーザーがDiscordに添付した画像URL、generate_imageの結果のimage_path、CanvaエクスポートURLなどを使える。"
        "事前にinstagram_statusでユーザーの連携状態を確認すること。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "image_url": {
                "type": "string",
                "description": "投稿する画像のURL（Discord添付URL、AI生成URL、CanvaエクスポートURLなど）",
            },
            "caption": {
                "type": "string",
                "description": "投稿のキャプション（自然な文章、ハッシュタグ含めてよい）",
            },
        },
        "required": ["image_url", "caption"],
    }

    def __init__(self, instagram_client):
        self.instagram = instagram_client

    async def execute(
        self, *, agent_context=None, image_url: str = "", caption: str = "", **kwargs
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not image_url:
            return ToolResult(success=False, error="image_urlが必要です")
        if not caption:
            return ToolResult(success=False, error="captionが必要です")

        discord_id = str(agent_context.message.author.id)

        connected = await self.instagram.is_connected(discord_id)
        if not connected:
            return ToolResult(success=False, error="Instagram未連携")

        result = await self.instagram.download_and_post(discord_id, image_url, caption)

        if result["success"]:
            return ToolResult(
                success=True,
                data={"media_id": result["media_id"], "media_url": result["media_url"]},
            )
        return ToolResult(success=False, error=result["error"])


class InstagramStatusTool(Tool):
    """Instagram連携状態確認ツール"""

    name = "instagram_status"
    max_calls_per_execution = 2
    description = (
        "ユーザーのInstagram連携状態を確認する。"
        "未連携の場合、WebUI https://rajitan.glareishiki.com から連携できることを案内する。"
    )
    parameters = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def __init__(self, instagram_client):
        self.instagram = instagram_client

    async def execute(self, *, agent_context=None, **kwargs) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")

        discord_id = str(agent_context.message.author.id)
        connected = await self.instagram.is_connected(discord_id)

        if connected:
            username = await self.instagram.get_ig_username(discord_id)
            return ToolResult(success=True, data=f"連携済み @{username}")
        return ToolResult(success=True, data="未連携")


class GenerateImageTool(Tool):
    """Nanobanana (Google Gemini) 画像生成ツール"""

    name = "generate_image"
    max_calls_per_execution = 2
    description = (
        "Nanobanana（Google Gemini）でAI画像を生成する。"
        "プロンプトから画像を作成し、画像URLを返す。"
        "Instagram投稿用の画像作成、イラスト生成などに使う。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "prompt": {
                "type": "string",
                "description": "生成する画像の説明（英語推奨、具体的に書くほど良い結果が出る）",
            },
        },
        "required": ["prompt"],
    }

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key

    async def execute(self, *, prompt: str = "", **kwargs) -> ToolResult:
        if not self.api_key:
            return ToolResult(success=False, error="GOOGLE_AI_API_KEYが設定されていません")
        if not prompt:
            return ToolResult(success=False, error="promptが必要です")

        try:
            import google.generativeai as genai

            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel("gemini-2.0-flash-exp")

            response = model.generate_content(
                [prompt],
                generation_config=genai.GenerationConfig(
                    response_modalities=["IMAGE"],
                ),
            )

            # Extract image data from response
            image_data = None
            for part in response.candidates[0].content.parts:
                if hasattr(part, "inline_data") and part.inline_data:
                    image_data = part.inline_data.data
                    break

            if not image_data:
                return ToolResult(success=False, error="画像生成に失敗しました（画像データなし）")

            # Save to temp file and return path as pseudo-URL for instagram_post
            # The instagram_post tool's download_and_post can handle file:// URLs
            # But better to save and serve via a temporary approach
            suffix = ".png"
            with tempfile.NamedTemporaryFile(
                suffix=suffix, delete=False, dir="/tmp"
            ) as f:
                f.write(image_data)
                tmp_path = f.name

            return ToolResult(
                success=True,
                data={"image_path": tmp_path},
            )

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return ToolResult(success=False, error=f"画像生成に失敗: {e}")


class CanvaDesignTool(Tool):
    """Canvaテンプレートからデザイン生成ツール"""

    name = "canva_design"
    max_calls_per_execution = 2
    description = (
        "Canvaのブランドテンプレートからデザインを生成し、画像URLを返す。"
        "Instagram投稿用の画像をテンプレートから作成する場合に使う。"
        "事前にユーザーがCanvaアカウントを連携している必要がある。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "template_id": {
                "type": "string",
                "description": "使用するCanvaブランドテンプレートのID",
            },
            "text_replacements": {
                "type": "object",
                "description": "テンプレート内のテキストフィールドの置換（例: {\"title\": \"今日のニュース\"}）",
            },
        },
        "required": ["template_id"],
    }

    def __init__(self, canva_client):
        self.canva = canva_client

    async def execute(
        self,
        *,
        agent_context=None,
        template_id: str = "",
        text_replacements: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> ToolResult:
        if agent_context is None:
            return ToolResult(success=False, error="agent_context is required")
        if not template_id:
            return ToolResult(success=False, error="template_idが必要です")

        discord_id = str(agent_context.message.author.id)

        connected = await self.canva.is_connected(discord_id)
        if not connected:
            return ToolResult(success=False, error="Canva未連携")

        image_url = await self.canva.create_and_export(
            discord_id, template_id, text_replacements
        )

        if image_url:
            return ToolResult(success=True, data={"image_url": image_url})
        return ToolResult(success=False, error="Canvaデザインの生成に失敗")
