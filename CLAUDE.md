# interview-agent

面试复习 Agent:CLI 出题 → 用户口述答案 → LLM 对照评分要点(rubric)判分落库 → 错题优先重现。Phase 1 已上线:https://github.com/Wave-Han/interview-agent

## 常用命令

```bash
python -m pytest -q                                    # 全量测试(22 个)
python -m interview_agent quiz --topic jvm             # 开练(topic: jvm/thread_pool/mysql/network/os/redis/netty_algo/agent)
python -m interview_agent quiz --topic jvm --wrong-only # 只打错题
```

## 架构速览

| 模块 | 职责 |
|------|------|
| `interview_agent/__main__.py` | CLI 入口(quiz 子命令、错误分流、Ctrl+C 统计) |
| `interview_agent/session.py` | SessionDriver:ask() 直连选题工具(不走 LLM);grade() 注入 rubric 进 run_agent 判题 |
| `interview_agent/agent/loop.py` | 手写 ReAct 循环(tool_calls → 执行 → tool_result 回填;20 次安全阀) |
| `interview_agent/llm/client.py` | OpenAI 兼容薄抽象(httpx 直连,不用官方 SDK),指数退避 ×3 |
| `interview_agent/tools/` | pick_question / record_result / get_stats;registry.execute 永不抛异常 |
| `interview_agent/store/` | SQLite 三表(questions/attempts/wrong_notes);错题状态机:连对 2 次 → mastered |

## 硬性约定(改代码前必读)

- **模型填表,代码干活**:判题的 question_id 必须在 rubric 消息首行显式给模型;展示给用户的点评一律取自 DB 的 feedback(latest_feedback),不信模型自由文本(历史教训:模型会幻演判题消息模板)。
- **SQL 零方言**:不用 ON CONFLICT / AUTOINCREMENT 之外的 SQLite 特性;错题状态机计算在 Python 侧(MySQL 的 SET 从左到右求值,SQL 侧自增列会改变语义)。唯一豁免:`datetime('now')`。
- 注释英文;面向用户的输出中文。
- 依赖白名单:httpx、python-dotenv、pytest(dev)。禁止引入 LLM 官方 SDK / LangChain。
- 用户答案一律用 `=== USER ANSWER START/END ===` 定界 + prompt 声明 untrusted(防注入操纵判分)。
- 选题策略:未掌握错题全局优先(刻意设计)、本会话已问排除(exclude_ids,"稍后再见"非"立刻重考")。

## 流程

- 小改动:直接改 + pytest 绿 + commit,不进 plan。
- 新特性:先 brainstorming 出 spec(`docs/superpowers/specs/`),大特性走 subagent-driven-development(历史 spec/plan 在 `docs/superpowers/` 有完整留痕)。
- 真实 LLM 行为改动必须真实 API 冒烟——mock 验证逻辑,冒烟验证行为(两个生产 bug 都是冒烟抓的)。

## Phase 2 待办(终审遗留 fix-later)

重试语义收紧(末次失败后不 sleep;401/403 不重试)· 种子库 4 处复合要点拆分(q6/q40/q65/q70)· registry 异常路径测试 · 题面/输出进一步美化 · RAG 题库检索 + Redis 会话记忆 · httpx Client 连接复用(可选)
