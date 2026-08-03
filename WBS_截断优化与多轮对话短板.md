# WBS：截断优化（A 组）与多轮对话短板修复（B 组）

> 关联设计文档：`设计_截断优化与多轮对话短板.md`（artifact）
> 状态更新日期：2026-08-02

## WBS-1：WBS 分解

| 子任务 | 状态 |
|---|---|
| 1.1 按"WBS→设计→评审→开发→测试→E2E→启动服务"拆解为 8 阶段 | ✅ completed |
| 1.2 定义每阶段交付物与验收口径 | ✅ completed |

## WBS-2：设计

| 子任务 | 状态 |
|---|---|
| 2.1 检索上下文预算双约束设计（单源 8000 / 总量 200000 / 存储 12000） | ✅ completed |
| 2.2 多轮对话 4 项短板修复设计（历史窗口化注入、会话摘要压缩、实体记忆、checkpointer 可观测） | ✅ completed |
| 2.3 输出设计文档 `设计_截断优化与多轮对话短板.md` | ✅ completed |

## WBS-3：评审

| 子任务 | 状态 |
|---|---|
| 3.1 第二模型交叉审查（DeepSeek 作第二模型，等效 Oracle 协议） | ✅ completed |
| 3.2 审查结论：2 P0 + 7 P1，输出 `_review_design_result.txt` | ✅ completed |
| 3.3 设计文档应用全部评审修正 | ✅ completed |

## WBS-4：开发（A 组截断优化）

| 子任务 | 状态 |
|---|---|
| 4.1 `config.py` 新增 7 项配置（retrieval_* 3 项 + history_* 4 项） | ✅ completed |
| 4.2 新增 `nodes/context_budget.py`（allocate_per_source_chars / truncate_with_ellipsis） | ✅ completed |
| 4.3 新增 `nodes/history_utils.py`（smart_truncate / summarize_oldest / apply_total_budget / update_entity_memory） | ✅ completed |
| 4.4 `retrieve.py`、`final_search.py` 状态层截断 3000→12000 动态化 | ✅ completed |
| 4.5 `evaluate.py` 注入侧动态预算 + 历史 smart_truncate | ✅ completed |
| 4.6 `dailymed.py` 源内截断参数化 + 多 SPL 前 2 个拼接钳制 | ✅ completed |

## WBS-5：开发（B 组多轮对话短板）

| 子任务 | 状态 |
|---|---|
| 5.1 `state.py` 新增 session_summary / summary_rounds / entity_memory / compressed_this_round | ✅ completed |
| 5.2 `graph.py` CHECKPOINTER_STATE + get_checkpointer_status + 压缩触发挂载 | ✅ completed |
| 5.3 `understand.py` 实体记忆注入 + 历史可配置窗口 + apply_total_budget | ✅ completed |
| 5.4 `main.py` lifespan 显式图探测 + health 暴露 checkpointer 状态 | ✅ completed |

## WBS-6：测试

| 子任务 | 状态 |
|---|---|
| 6.1 单元测试 `test_context_budget.py` 20/20 | ✅ completed |
| 6.2 集成测试 `test_integration_memory.py` 4/4（含 checkpointer 降级告警验证） | ✅ completed |
| 6.3 既有 E2E `e2e_verify.py` 28/28 全绿 | ✅ completed |
| 6.4 新增多轮记忆 E2E `e2e_memory_verify.py` 5/5 | ✅ completed |

## WBS-7：E2E 与断言修正

| 子任务 | 状态 |
|---|---|
| 7.1 重启后重跑既有 E2E：search quality / answer 长度 2 个 FAIL 消除 | ✅ completed |
| 7.2 修正增量流式断言缺陷（首分块→拼接全量答案；no-buffering 检测与 LLM 首响应延迟解耦） | ✅ completed |
| 7.3 最终全量回归：既有 E2E 28/28 + 记忆 E2E 5/5 | ✅ completed |

## WBS-8：启动服务与交付

| 子任务 | 状态 |
|---|---|
| 8.1 停止旧进程（PID 13260）并重启服务（PID 16668，18082 端口就绪） | ✅ completed |
| 8.2 health 验证：checkpointer backend=memory / degraded=true / 新代码已加载 | ✅ completed |
| 8.3 向用户交付验收汇总 | ✅ completed |
