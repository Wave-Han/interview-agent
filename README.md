# interview-agent

AI Agent 驱动的命令行刷题工具:针对 Java 后端 / AI Agent 方向的面试题,对你输入的自由文本作答,由 LLM 按**评分点(rubric)逐条比对**给出 0~1 得分与中文点评,错题自动进入错题本,**下次启动优先重现**,直到连续答对两次才移出复习队列。

纯 Python 实现,不依赖 LangChain 等框架:工具调用协议、ReAct 循环、错题状态机全部手写,适合作为 Agent 工程的最小可读样例。

## 架构

```
                    ┌─────────────────────────────────────────────┐
                    │  __main__.py (CLI: argparse + 交互循环)      │
                    └──────────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────┐
                    │  session.py  SessionDriver                  │
                    │  ask()   = 直接调 pick_question,不经过 LLM   │
                    │  grade() = 注入 rubric 后交给 run_agent 判题 │
                    └───────┬──────────────────────────┬──────────┘
                            │                          │
              ┌─────────────▼────────────┐   ┌─────────▼──────────────┐
              │ agent/loop.py            │   │ tools/                 │
              │ 手写 ReAct 循环           │──▶│ pick_question          │
              │ (max_tool_calls 安全阀)   │   │ record_result          │
              └─────────────┬────────────┘   │ get_stats              │
                            │                └─────────┬──────────────┘
              ┌─────────────▼────────────┐   ┌─────────▼──────────────┐
              │ llm/client.py            │   │ store/  (SQLite)       │
              │ OpenAI 兼容协议           │   │ questions / attempts / │
              │ httpx + 3 次指数退避重试   │   │ wrong_notes 错题状态机  │
              └──────────────────────────┘   └────────────────────────┘
```

一轮问答的完整链路:`pick_question` 选出题目(出题不走 LLM,零 token 开销)→ 终端展示、你输入作答 → 题目的 `answer_points` 评分点连同你的回答注入 `run_agent`,由模型在 ReAct 循环中调 `record_result` 落库并输出点评 → Ctrl+C 随时退出并打印该 topic 的统计。

## 快速开始(30 秒)

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API key(默认指向智谱 GLM)
cp .env.example .env   # Windows: copy .env.example .env
# 编辑 .env,填入你的 LLM_API_KEY

# 3. 开刷
python -m interview_agent quiz --topic jvm
```

- 可选 topic:`jvm` / `thread_pool` / `mysql` / `network` / `os` / `redis` / `netty_algo` / `agent`
- `--wrong-only`:只复习错题本;Ctrl+C 退出时打印本次统计(答题数 / 平均分 / 未掌握错题数)

## 切换模型厂商

LLM 调用走标准 OpenAI `/chat/completions` 协议,换厂商只需改 `.env` 两个变量,**零代码改动**:

```dotenv
# DeepSeek 示例
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-chat

# Kimi 示例
LLM_BASE_URL=https://api.moonshot.cn/v1
LLM_MODEL=moonshot-v1-8k
```

## 两个刻意设计的行为

1. **错题优先是全局的。** 你指定了 `--topic jvm`,但任何 topic 下未掌握的错题都会先于 jvm 新题出现。这是刻意的复习策略:错过的题比新题重要,答对两次(掌握)之前,它会一直插队。
2. **启动时自动导入种子题库。** CLI 每次启动会把包内 `interview_agent/data/questions.json`(70 题、8 个 topic)导入 SQLite,按 id 去重,重复运行不会重复导入;你后续自建的新题不受影响。

## Roadmap

| Phase | 内容 |
|-------|------|
| P1(当前) | CLI 刷题 + LLM 按评分点判题 + 错题优先重现 |
| P2 | RAG 题库检索 + Redis 会话记忆 |
| P3 | 多 Agent(出题 / 判题分离)+ Eval 黄金集 |
| P4 | Spring Boot Web 版 |

## 开发

```bash
pytest -v          # 20 个测试,无需真实 API key(全部 mock)
```
