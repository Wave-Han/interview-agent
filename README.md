# interview-agent

AI Agent 驱动的命令行刷题工具:针对 Java 后端 / AI Agent 方向的面试题,对你输入的自由文本作答,由 LLM 按**评分点(rubric)逐条比对**给出 0~1 得分与中文点评,错题自动进入错题本,**下次启动优先重现**,直到连续答对两次才移出复习队列。

纯 Python 实现,不依赖 LangChain 等框架:工具调用协议、ReAct 循环、错题状态机、RAG 检索全部手写,适合作为 Agent 工程的最小可读样例。

## 架构

```
                    ┌─────────────────────────────────────────────┐
                    │  __main__.py (CLI: quiz / index / ask)       │
                    └──────────────────────┬──────────────────────┘
                                           │
                    ┌──────────────────────▼──────────────────────┐
                    │  session.py  SessionDriver(quiz 主循环)      │
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
              │ chat + embed(64/批向量)  │   │ questions / attempts / │
              │ httpx + 指数退避重试 ×3   │   │ wrong_notes / vectors  │
              └─────────────┬────────────┘   └─────────┬──────────────┘
                            │                          │
              ┌─────────────▼────────────┐   ┌─────────▼──────────────┐
              │ rag/                     │   │ session_store.py       │
              │ retriever:手写 cosine 检索│   │ Protocol 三实现        │
              │ qa:ask 固定回答管线       │   │ memory/SQLite/Redis    │
              │ (index/ask 子命令走这里)  │   │ 工厂探测,不可用自动降级 │
              └──────────────────────────┘   └────────────────────────┘
```

一轮 quiz 的完整链路:`pick_question` 选出题目(出题不走 LLM,零 token 开销)→ 终端展示、你输入作答 → 题目的 `answer_points` 评分点连同你的回答注入 `run_agent`,由模型在 ReAct 循环中调 `record_result` 落库并输出点评 → Ctrl+C 随时退出并打印该 topic 的统计。

`ask` 的 RAG 链路:`index` 把「题面 + 评分点」整体编码为向量(64 条/批)存入 SQLite → `ask` 用同一向量模型编码你的提问 → 手写 cosine 取 top-3 命中 → 命中题的题面与评分点作为参考资料注入固定模板,由 LLM 生成回答并附「接着练」推荐。检索为手写 cosine(题库规模 70,万级再考虑 ANN)。

## 快速开始(30 秒)

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 API key(默认指向智谱 GLM)
cp .env.example .env   # Windows: copy .env.example .env
# 编辑 .env,填入你的 LLM_API_KEY

# 3. 建 RAG 索引 + 开刷
python -m interview_agent index
python -m interview_agent quiz --topic jvm
```

## 命令一览

```bash
python -m interview_agent quiz --topic jvm               # 交互刷题(错题优先重现)
python -m interview_agent quiz --topic jvm --wrong-only  # 只复习错题本
python -m interview_agent quiz --topic jvm --resume      # 恢复该 topic 上次会话,接着刷
python -m interview_agent index                          # 建/重建向量索引(改题后须重跑)
python -m interview_agent ask "为什么三次握手不能两次"     # RAG 问答:自由提问,命中题库作答
```

- 可选 topic:`jvm` / `thread_pool` / `mysql` / `network` / `os` / `redis` / `netty_algo` / `agent`
- `--resume` 从会话存储恢复上次完整对话(按 topic 存取);`ask` 需先跑过一次 `index`,否则会提示
- Ctrl+C 退出时打印本次统计(答题数 / 平均分 / 未掌握错题数)

## 配置(.env)

| 变量 | 默认 | 说明 |
|------|------|------|
| `LLM_BASE_URL` | 智谱 | OpenAI 兼容接口地址 |
| `LLM_API_KEY` | — | 必填 |
| `LLM_MODEL` | `glm-4-flash` | 判题模型 |
| `EMBEDDING_MODEL` | `embedding-3` | 向量模型(`index` / `ask` 使用) |
| `DB_PATH` | `interview.db` | SQLite 路径 |
| `REDIS_URL` | 空 | 可选;未配置或 Redis 不可用时自动降级 SQLite 会话存储 |

依赖仅 httpx、python-dotenv、redis、pytest(dev)。其中 **redis 为可选运行时**:未安装该包、未配置 `REDIS_URL` 或 Redis 连不上时,会话自动落到 SQLite,完全不影响使用。

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
2. **启动时自动导入种子题库。** CLI 每次启动会把包内 `interview_agent/data/questions.json`(70 题、8 个 topic)导入 SQLite,按 id 去重,重复运行不会重复导入;你后续自建的新题不受影响(新增题后记得重跑 `index`)。

## Roadmap

| Phase | 内容 |
|-------|------|
| P1 ✅ | CLI 刷题 + LLM 按评分点判题 + 错题优先重现 |
| P2 ✅ | RAG 题库检索(index/ask)+ 会话存储与恢复(Redis/SQLite,自动降级) |
| P3(下一步) | 多 Agent(出题 / 判题分离)+ Eval 黄金集 |
| P4(可选) | Web 界面(Spring Boot) |

## 开发

```bash
pytest -v          # 44 个测试,无需真实 API key(全部 mock)
```
