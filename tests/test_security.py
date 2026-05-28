"""
Confirm tool error paths don't leak the token, server path, or the user's home
directory. These three are the only secrets the server knows about.
"""

from pathlib import Path


async def test_error_does_not_leak_token(call_tool, server):
    r = await call_tool("read_file", {"path": "Z:/definitely/not/here.txt"})
    assert "error" in r
    assert server.token not in r["error"]


async def test_error_redacts_home(call_tool):
    home = str(Path.home())
    fake = f"{home}/__definitely_not_a_real_file_xyzzy__.txt"
    r = await call_tool("read_file", {"path": fake})
    assert "error" in r
    assert home not in r["error"]
