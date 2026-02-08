import httpx

from rajitan.agent.tools.base import Tool, ToolResult
from rajitan.utils.config import get_config
from rajitan.utils.logger import get_logger

logger = get_logger("agent.tools.web_search")


class WebSearchTool(Tool):
    name = "web_search"
    description = "Brave Searchでウェブを検索する。最新情報、ニュース、知識の確認に使う。"
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
        self.api_key = config.brave_search_api_key

    async def execute(self, *, query: str = "", **kwargs) -> ToolResult:
        if not self.api_key:
            return ToolResult(success=False, error="Brave Search APIキーが設定されていない")

        if not query:
            return ToolResult(success=False, error="検索クエリが空です")

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    headers={
                        "X-Subscription-Token": self.api_key,
                        "Accept": "application/json",
                    },
                    params={
                        "q": query,
                        "count": 5,
                    },
                )
                response.raise_for_status()
                web_results = response.json().get("web", {}).get("results", [])

            results = []
            for item in web_results[:5]:
                results.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("description", ""),
                })

            if not results:
                return ToolResult(success=True, data="検索結果が見つかりませんでした。")

            return ToolResult(success=True, data=results)

        except httpx.HTTPStatusError as e:
            body = e.response.text[:300]
            logger.error(f"Brave Search API error: {e.response.status_code} — {body}")
            return ToolResult(success=False, error=f"検索APIエラー: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Web search failed: {e}")
            return ToolResult(success=False, error=f"検索に失敗: {e}")
