import httpx

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.config import get_config
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.web_search")


class WebSearchTool(Tool):
    name = "web_search"
    description = "Google検索でWebを検索する。最新情報、ニュース、知識の確認に使う。"
    max_calls_per_execution = 2
    parameters = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "検索クエリ",
            },
        },
        "required": ["query"],
    }

    def __init__(self):
        config = get_config()
        self.api_key = config.google_search_api_key
        self.cx = config.google_search_cx

    async def execute(self, *, query: str = "", **kwargs) -> ToolResult:
        if not self.api_key or not self.cx:
            return ToolResult(success=False, error="Google Search APIが設定されていない")

        if not query:
            return ToolResult(success=False, error="検索クエリが空です")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://www.googleapis.com/customsearch/v1",
                    params={
                        "key": self.api_key,
                        "cx": self.cx,
                        "q": query,
                        "num": 5,
                    },
                )
                response.raise_for_status()
                items = response.json().get("items", [])

            results = []
            for item in items[:5]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("link", ""),
                    "snippet": item.get("snippet", ""),
                })

            if not results:
                return ToolResult(success=True, data="検索結果が見つかりませんでした。")

            return ToolResult(success=True, data=results)

        except httpx.HTTPStatusError as e:
            logger.error(f"Google Search API error: {e.response.status_code}")
            return ToolResult(success=False, error=f"検索APIエラー: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(success=False, error=f"検索に失敗: {e}")
