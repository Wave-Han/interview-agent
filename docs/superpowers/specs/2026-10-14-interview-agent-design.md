# 面试复习 Agent(Interview Agent)— 设计文档

- 日期:2026-10-14
- 状态:已与用户逐节确认,待最终审阅
- 阶段:**Phase 1(CLI 复习工具)**——本文档只覆盖 Phase 1

## 1. 背景与目标

用户(Java 后端,校招准备中,同时转向 AI Agent 方向)需要把过去一个月的"人肉复习模式"(出题 → 口述作答 → 对照要点判分 → 错题优先重现)代码化为一个可运行的 Agent 作品集项目。

**成功标准:**
1. 作品集:能在面试中演示"手写 agent loop + 工具调用 + 错题本存储"的完整链路;
2. 实用:用户日常真的用它复习(每天 15 分钟模式);
3. 可演进:Phase 2~4(RAG / Redis 记忆 / 多 Agent / Spring Boot Web)在此地基上叠加。

## 2. 已确认的关键决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| LLM 接入 | OpenAI 兼容薄抽象层,默认智谱 GLM | 换 `base_url`/`model` 即可切 DeepSeek/Kimi;简历可写"多模型可切换" |
| 语言 | Python(Phase 1~3),Java Spring Boot(Phase 4 Web) | Python 迭代快;Java 保留本命栈 |
| 存储 | SQLite | 零运维、SQL 写法对齐 MySQL、可平滑迁移 |
| 架构 | 手写核心 + 分层包结构(不用 LangChain) | 作品集价值在"自己实现了循环",不在调包 |

## 3. Phase 1 范围

**做:**
- CLI:`python -m interview_agent quiz --topic <t>` 与 `--wrong-only`
- 会话流程:出题 → 用户口述答案 → Agent 对照 `answer_points` 判题(LLM-as-judge)→ 落库 → 错题进错题本 → 优先重现
- 首次运行自动导入种子题库(~70 题)

**不做(后续 Phase):**
- Phase 2:RAG 题库检索(向量库)、Redis 会话短期记忆
- Phase 3:出题者/判题者多 Agent、Eval 黄金集
- Phase 4:Spring Boot Web 界面

## 4. 架构与数据流

```
interview_agent/
├─ __main__.py        # CLI 入口(quiz 命令、参数解析)
├─ config.py          # .env 读取(base_url / model / api_key / db_path)
├─ llm/
│  └─ client.py       # LLMClient:OpenAI 兼容 chat(messages, tools) + 重试
├─ agent/
│  └─ loop.py         # 手写 ReAct 循环(状态机)
├─ tools/
│  ├─ registry.py     # 工具注册表(name -> handler + schema)
│  ├─ pick_question.py
│  ├─ record_result.py
│  └─ get_stats.py
├─ store/
│  ├─ db.py           # 连接与建表(内存 SQLite 供测试)
│  ├─ questions.py
│  └─ attempts.py     # 含 wrong_notes 逻辑
├─ data/
│  └─ questions.json  # 种子题库
└─ tests/
```

**一次问答的数据流:**
```
CLI 收到用户答案 → messages 追加 user → LLMClient.chat(messages, tools)
→ 若返回 tool_calls:分发到 handler 执行 → 结果以 tool 角色回填 → 继续
→ 若无 tool_calls(纯文本):打印给用户(出题/判题点评都是模型文本输出)
判题评分落库由模型调用 record_result 工具完成(模型填表,代码干活)
```

**职责切分(关键设计):**
- **判题由主 Agent 承担**——system prompt 中给出题面、用户答案、`answer_points`,要求模型输出点评并调用 `record_result`;
- **工具只做确定性的活**:选题策略、落库、统计——不含二次 LLM 调用。

## 5. 核心组件

### 5.1 llm/client.py
- `LLMClient.chat(messages, tools=None) -> dict`(OpenAI 兼容响应)
- 重试:指数退避(1s/2s/4s)×3,仍失败抛 `LLMConnectionError`
- 不用官方 SDK,用 `httpx` 直连(薄抽象,零依赖锁定)

### 5.2 agent/loop.py
- `run_agent(client, tools_registry, system, user_input, on_output) `
- 状态机:`while` 响应含 `tool_calls` → 执行 → 回填;`finish_reason != "tool_calls"` → 返回最终文本
- 安全阀:单轮会话最多 20 次工具调用(防死循环烧钱)
- 工具异常:捕获后以 `{"error": ...}` 作为 tool 消息回传(不吞错,让模型自纠)

### 5.3 tools(三个)
| 工具 | 输入 | 行为 |
|------|------|------|
| `pick_question` | `topic: str, wrong_only: bool=false` | 错题优先(wrong_notes 未 mastered 的先出),否则按"最久未答"选;返回题面 + 隐藏 answer_points 不给模型(防泄题)——判题时由 CLI 侧注入 |
| `record_result` | `question_id, score: 0~1, feedback: str` | 写 attempts;score<0.6 → upsert wrong_notes(wrong_count+1);score≥0.6 且在错题本 → 连对计数,连续 2 次对 → mastered=1 |
| `get_stats` | `topic: str` | 返回该 topic 答题数、平均分、错题数 |

## 6. 数据模型

```sql
CREATE TABLE questions (
  id INTEGER PRIMARY KEY,
  topic TEXT NOT NULL,
  difficulty INTEGER DEFAULT 2,
  question TEXT NOT NULL,
  answer_points TEXT NOT NULL   -- JSON array of str
);
CREATE TABLE attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES questions(id),
  user_answer TEXT NOT NULL,
  score REAL NOT NULL,
  feedback TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE wrong_notes (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id),
  wrong_count INTEGER DEFAULT 1,
  streak_right INTEGER DEFAULT 0,
  mastered INTEGER DEFAULT 0,
  last_wrong_at TEXT
);
```
(避免 SQLite 特有方言,保持与 MySQL 兼容的心智;`datetime('now')` 一处例外,迁移时替换为 MySQL `NOW()`。)

种子题库 `data/questions.json`:每模块 8~10 题,topics = jvm / thread_pool / mysql / network / os / redis / netty_algo / agent;`answer_points` 即判题 rubric(源自真实学习沉淀,含历史错题)。

## 7. 错误处理
- LLM 连接失败:重试 3 次(指数退避)→ 抛错退出,退出前已落库的 attempts 不受影响;
- 工具执行失败:回传 error 给模型(模型可重试或换路),连续 3 次同工具失败则终止会话;
- 用户中断(Ctrl+C):捕获,打印本会话统计后退出。

## 8. 测试策略(pytest)
- `store/`:内存 SQLite 真测(建表、选题策略、错题 mastered 状态机);
- `llm/`:mock httpx(不花钱,验证重试逻辑);
- `agent/loop.py`:脚本化 fake client(预设 tool_calls 序列),验证状态机与安全阀;
- 不做 LLM 真连的自动化测试(成本与不稳定性),真连验证放在手工验收。

## 9. 验收标准(Phase 1 DoD)
1. `python -m interview_agent quiz --topic jvm` 完整跑通:出题 → 判题(给分+点评)→ 落库;
2. 答错的题在 `--wrong-only` 中优先出现;
3. `.env` 改 `base_url`+`model` 切换模型商,不改代码;
4. `pytest` 全绿;
5. `README.md` 一页:架构图 + 30 秒上手 + 配置说明;
6. git 历史清晰(按组件分 commit)。

## 10. 配置样例(.env,不入库)
```
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=sk-xxx
LLM_MODEL=glm-4-flash
DB_PATH=interview.db
```

## 11. 后续 Phase 展望(仅记录,不在本期实现)
- Phase 2:RAG(题库切块入向量库,支持自由提问式复习)、Redis 会话记忆(Hash + TTL,滑动过期)
- Phase 3:多 Agent(出题者/判题者分离,验证上下文隔离)、Eval 黄金集(20 题固定判题准确率)
- Phase 4:Spring Boot Web(FastAPI 亦可,由用户届时定)
