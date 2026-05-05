import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def query_mcp_server(topic: str) -> str:
    keywords = ["codebase", "repo", "architecture", "refactor", "bug"]
    if not any(k in topic.lower() for k in keywords):
        return ""
        
    print("\n[🔌 MCP Client] Connecting to code-review-graph local MCP Server...")
    try:
        server_params = StdioServerParameters(
            command="python",
            args=["-m", "code_review_graph"]
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                
                # Fetch minimal context
                result = await session.call_tool("get_minimal_context_tool", arguments={
                    "task": topic[:200]
                })
                
                context = ""
                for c in result.content:
                    if c.type == "text":
                        context += c.text + "\n"
                        
                if context:
                    print("[✅ MCP Client] Successfully fetched codebase context.")
                    return f"\n--- MCP LOCAL CODEBASE CONTEXT ---\n{context}\n"
                return ""
    except Exception as e:
        print(f"[❌ MCP Client Error]: {e}")
        return ""
