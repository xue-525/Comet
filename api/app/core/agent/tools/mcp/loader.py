"""MCP 工具加载：基于官方 langchain-mcp-adapters 把外部 MCP server 工具转成 LangChain 工具。

- build_mcp_tools：问答时调用，读已启用 server → 加载其工具，工具名清洗+加 server 前缀+去重。
- fetch_tools_meta：test/sync 时调用，连单个 server 拉工具清单（原始 name/description）。
单个 server 失败降级跳过，不影响其余 server 与内置工具。

工具名约束：OpenAI function calling 要求工具名匹配 ^[a-zA-Z0-9_-]+$ 且不超过 64 字符，
故对 server 名与 MCP 原始工具名统一清洗（非法字符替换为 _），并去重。
"""
import re
import time
import uuid

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.tools import load_mcp_tools
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent.tools.mcp.connection import build_connection
from app.core.logging import get_logger
from app.models.mcp_server_model import MCPServer
from app.repositories.mcp_server_repository import MCPServerRepository

logger = get_logger(__name__)

_INVALID = re.compile(r"[^a-zA-Z0-9_-]")
_MAX_NAME_LEN = 64

# 进程内 MCP 工具缓存：避免每轮对话都重连 server 拉工具清单（握手+协商耗时）。
# key=user_id，value=(过期时间戳, server 指纹, 工具列表)。指纹变化（增删/改 server）即失效。
_MCP_CACHE: dict[str, tuple[float, str, list[BaseTool]]] = {}
_MCP_CACHE_TTL = 300.0  # 秒


def _servers_fingerprint(servers: list[MCPServer]) -> str:
    """已启用 server 的指纹：id + updated_at，任一变化即缓存失效。"""
    parts = [
        f"{s.id}:{s.updated_at.isoformat() if s.updated_at else ''}"
        for s in servers
    ]
    return "|".join(sorted(parts))


def _sanitize(text: str) -> str:
    """清洗为合法工具名片段：非法字符→_，去首尾下划线；空则回退 'mcp'。"""
    cleaned = _INVALID.sub("_", text).strip("_")
    return cleaned or "mcp"


async def _load_raw_tools(server: MCPServer) -> list[BaseTool]:
    """连接单个 server 加载原始工具（不改名）。"""
    conn = build_connection(server)
    return await load_mcp_tools(None, connection=conn)


def _rename(tool: BaseTool, prefix: str, seen: set[str]) -> None:
    """把工具名清洗为合法名（{prefix}__{tool}），并在 seen 内去重。"""
    base = f"{prefix}__{_sanitize(tool.name)}"[:_MAX_NAME_LEN]
    name = base
    i = 1
    while name in seen:
        suffix = f"_{i}"
        name = base[: _MAX_NAME_LEN - len(suffix)] + suffix
        i += 1
    seen.add(name)
    tool.name = name


async def build_mcp_tools(
    session: AsyncSession, user_id: uuid.UUID
) -> list[BaseTool]:
    """构建该用户所有已启用 MCP server 的工具列表（名称清洗+去重）。

    带进程内 TTL 缓存：server 配置未变（指纹一致）且未过期时复用，避免每轮重连握手。
    """
    servers = await MCPServerRepository(session).list_by_user(
        user_id, enabled_only=True
    )
    uid = str(user_id)
    fingerprint = _servers_fingerprint(servers)
    now = time.monotonic()
    cached = _MCP_CACHE.get(uid)
    if cached and cached[0] > now and cached[1] == fingerprint:
        return list(cached[2])  # 复用缓存（返回副本，避免外部改名污染缓存）

    tools: list[BaseTool] = []
    seen: set[str] = set()
    for server in servers:
        try:
            raw = await _load_raw_tools(server)
        except Exception as e:
            logger.warning("加载 MCP 工具失败（跳过）: %s: %s", server.name, e)
            continue
        prefix = _sanitize(server.name)
        for t in raw:
            _rename(t, prefix, seen)
            tools.append(t)
    # 仅在全部 server 都成功（无跳过）时缓存，避免把"部分失败"的残缺列表缓存住
    _MCP_CACHE[uid] = (now + _MCP_CACHE_TTL, fingerprint, list(tools))
    return tools


def invalidate_mcp_cache(user_id: uuid.UUID | str | None = None) -> None:
    """清除 MCP 工具缓存（增删/改 server 或测试连接后调用）。None=全部清。"""
    if user_id is None:
        _MCP_CACHE.clear()
    else:
        _MCP_CACHE.pop(str(user_id), None)


async def fetch_tools_meta(server: MCPServer) -> list[dict]:
    """连接 server 拉取工具清单元信息（原始名，用于测试连接 / 同步）。

    抛出异常由调用方捕获并记入 server.last_error。
    """
    tools = await _load_raw_tools(server)
    return [
        {"name": t.name, "description": (t.description or "")[:500]}
        for t in tools
    ]


__all__ = ["build_mcp_tools", "fetch_tools_meta", "invalidate_mcp_cache"]
