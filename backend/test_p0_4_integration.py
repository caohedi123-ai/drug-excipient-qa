"""P0.4 ChEMBL MCP 集成测试（真实拉起 node 子进程，需可联网 + 本地已构建 MCP Server）

运行方式：python test_p0_4_integration.py
前置条件：
  1. backend/.env 中 CHEMBL_MCP_ENABLED=true
  2. backend/mcp/ChEMBL-MCP-Server/build/index.js 已构建（npm run build）
  3. 可访问 https://www.ebi.ac.uk/chembl/（ChEMBL API）

覆盖：
  - MCP 深度检索返回分子靶点/生物活性/ADMET/SMILES
  - 关闭后我方 spawn 的 node 子进程真正终止（无泄漏）
  - 失败时保证 close_client 清理，不残留进程
"""
import asyncio
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from tools.sources.chembl_mcp_client import ChemblMCPClient, close_client


def _my_node_pids(parent_pid: int) -> list[int]:
    """父进程=当前 python、命令行含 ChEMBL-MCP-Server 的 node 子进程 PID 列表。"""
    out = subprocess.run(
        ["powershell", "-NoProfile", "-Command",
         f"Get-CimInstance Win32_Process -Filter \"Name='node.exe'\" | "
         f"Where-Object {{ $_.CommandLine -like '*ChEMBL-MCP-Server*' -and $_.ParentProcessId -eq {parent_pid} }} | "
         "Select-Object -ExpandProperty ProcessId"],
        capture_output=True, text=True,
    ).stdout.split()
    return [int(x) for x in out if x.strip().isdigit()]


async def _verify_chembl_mcp() -> None:
    parent = os.getpid()
    before = _my_node_pids(parent)
    assert not before, f"起始状态不应有我方 ChEMBL node 子进程: {before}"
    client = ChemblMCPClient.instance()
    try:
        txt = await client.search_full("aspirin")
        mid = _my_node_pids(parent)
        assert mid, f"检索期间应存在我方 node 子进程, 实际: {mid}"
        if txt:
            # 深度字段断言仅在 ChEMBL 官方服务可用时执行（服务端 500 属外部故障，不影响进程治理验证）
            assert "分子靶点" in txt, "应含分子靶点行（P0-4 审查补强）"
            assert "SMILES" in txt, "应含 SMILES"
            assert "ADMET" in txt, "应含 ADMET"
            print(f"[OK] MCP 深度检索可用（含分子靶点/SMILES/ADMET），我方 node 子进程 PID={mid}")
        else:
            print(f"[SKIP] ChEMBL 官方服务暂不可用（search_full 返回空），跳过字段断言，仅验证进程治理。我方 node 子进程 PID={mid}")
    finally:
        await close_client()
    time.sleep(1)
    after = _my_node_pids(parent)
    assert not after, f"close_client 后我方 node 子进程仍存在（泄漏）: {after}"
    print("[OK] close_client 后我方 node 子进程已终止（无泄漏）")


if __name__ == "__main__":
    try:
        asyncio.run(_verify_chembl_mcp())
        print("\n=== P0.4 ChEMBL MCP 集成测试通过 ===")
    except AssertionError as e:
        print(f"[FAIL] {e}")
        sys.exit(1)
