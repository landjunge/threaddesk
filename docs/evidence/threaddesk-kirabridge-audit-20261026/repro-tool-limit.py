"""Run with KiraBridge PYTHONPATH=src and its existing .venv/bin/python."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from kirabridge.threaddesk_dynamic import _fresh_tools
from kirabridge.bridge_core.models import BridgeError

async def main():
    def tool(name, read):
        return SimpleNamespace(name=name, description='example', inputSchema={'type': 'object'}, annotations=SimpleNamespace(readOnlyHint=read, destructiveHint=False))
    tools = [tool('reader', True)] + [tool(f'writer{i}', False) for i in range(64)]
    manager = SimpleNamespace(connect=AsyncMock(), settings=SimpleNamespace(timeout=2), pool=SimpleNamespace(list_tools=AsyncMock(return_value=tools)))
    try:
        print(await _fresh_tools(manager))
    except BridgeError as exc:
        print('65 declared tools including 1 eligible read =>', exc.code)

asyncio.run(main())
