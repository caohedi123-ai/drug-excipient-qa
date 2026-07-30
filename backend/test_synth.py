import sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from agent.nodes.evaluate import SYNTHESIZE_PROMPT

# 1) 验证 format 不抛异常（重点排查大括号残留）
for it in ["comparison", "excipient_info", "safety", "mechanism", "未指定"]:
    out = SYNTHESIZE_PROMPT.format(
        results="[PubChem]\n阿司匹林（Aspirin）..." ,
        citations="[1] PubChem: https://pubchem.ncbi.nlm.nih.gov/compound/2244",
        query="阿司匹林和布洛芬有什么区别",
        intent=it,
    )
    assert "{intent}" not in out, "intent 占位符残留!"
    assert "{results}" not in out and "{citations}" not in out and "{query}" not in out, "占位符残留!"
    print(f"[OK] intent={it}  format成功 len={len(out)}")

# 2) 验证关键结构要素都在
probe = SYNTHESIZE_PROMPT.format(
    results="x", citations="y", query="q", intent="comparison"
)
for kw in ["质量三原则", "【详细】", "【逻辑支撑】", "【可读】", "## 总结", "📚 参考资料", "参考骨架", "结论前置"]:
    assert kw in probe, f"缺少关键要素: {kw}"
print("[OK] 质量三原则/总结/参考资料/意图驱动 全部存在")
print("PROMPT 自测通过")
