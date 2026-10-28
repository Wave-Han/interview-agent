# interview-agent

AI Agent 驱动的刷题工具(CLI + Web 双入口):针对 Java 后端 / AI Agent 方向的面试题,对你输入的自由文本作答,由 LLM 按**评分点(rubric)逐条比对**给出 0~1 得分与中文点评,错题自动进入错题本,**下次启动优先重现**,直到连续答对两次才移出复习队列。

核心纯 Python 实现,不依赖 LangChain 等框架:工具调用协议、ReAct 循环、错题状态机、RAG 检索全部手写,适合作为 Agent 工程的最小可读样例;Web 层(Phase 4)为 Spring Boot 页面 + FastAPI 薄适配,判题与 CLI 走同一条路径。

## 架构

```
                    ┌─────────────────────────────────────────────┐
                    │  __main__.py (CLI: quiz/index/ask/eval)     │
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
              │ chat + embed(向量)       │   │ questions / attempts / │
              │ httpx + 指数退避重试 ×3   │   │ wrong_notes / vectors  │
              └─────────────┬────────────┘   └─────────┬──────────────┘
                            │                          │
              ┌─────────────▼────────────┐   ┌─────────▼──────────────┐
              │ rag/                     │   │ session_store.py       │
              │ retriever:手写 cosine 检索│   │ Protocol 三实现        │
              │ qa:ask 固定回答管线       │   │ memory/SQLite/Redis    │
              │ (仅 ask 子命令经过这里) │   │ 工厂探测,不可用自动降级 │
              └──────────────────────────┘   └────────────────────────┘

              ┌─────────────────────────────────────────────┐
              │ eval/  生成器-评估器(仅 eval 子命令经过这里) │
              │ 黄金集逐案例过真实判题循环;                  │
              │ EvalRecorder 内存接收 record_result          │
              │ (存储隔离,eval 永不写学习表)                │
              └─────────────────────────────────────────────┘
```

一轮 quiz 的完整链路:`pick_question` 选出题目(出题不走 LLM,零 token 开销)→ 终端展示、你输入作答 → 题目的 `answer_points` 评分点连同你的回答注入 `run_agent`,由模型在 ReAct 循环中调 `record_result` 落库并输出点评 → Ctrl+C 随时退出并打印该 topic 的统计。

`ask` 的 RAG 链路:`index` 把「题面 + 评分点」整体编码为向量(64 条/批)存入 SQLite → `ask` 用同一向量模型编码你的提问 → 手写 cosine 取 top-3 命中 → 命中题的题面与评分点作为参考资料注入固定模板,由 LLM 生成回答并附「接着练」推荐。检索为手写 cosine(题库规模 70,万级再考虑 ANN)。

`eval` 的链路(生成器-评估器):黄金集 20 题 × good/partial/bad 三档共 60 案例,草稿由 `scripts/generate_golden.py` 盲生成(prompt 只含题面与档位行为描述,评分点绝不流入,防止答案照抄 rubric),再人工校对定分数区间 → `eval` 把每个案例的答案注入与 quiz 完全相同的判题 prompt(判题首轮同样以 `tool_choice` 强制调用 `record_result`),走同一个 ReAct 循环,唯一差别是 `record_result` 落进内存 `EvalRecorder`(存储隔离,eval 永不写学习表)→ 档位命中率表格打印,逐 case 明细报告写入 `docs/eval/report-<日期>.md`。

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
python -m interview_agent eval                            # 黄金集 eval:60 案例真实 API 判题,报告落盘 docs/eval/
```

## Web 界面(双服务,Phase 4)

CLI 之外的第二个入口:浏览器操作,判题、错题本与统计和 CLI **共用同一 SQLite 库、同一条判题链路**。

```
 浏览器
   │  页面路由:/practice · /stats · /ask(Thymeleaf + 原生 JS)
   ▼
┌────────────────────────────┐      ┌────────────────────────────────┐
│ Spring Boot 页面层(web/)    │ HTTP │ FastAPI AI 服务                 │
│ 端口 8080                   │────▶ │ interview_agent/server.py       │
│ /web/* 聚合端点             │ /api/*│ 端口 8000,4 端点薄适配          │
│ AiClientService 转发 + 降级 │      │ /api/question · /grade · ask · stats
└────────────────────────────┘      └───────────────┬────────────────┘
                                                    │ 进程内函数调用
                                                    ▼
                                        核心模块(与 CLI 同判题路径:
                                        run_agent + record_result,同一 SQLite)
```

一键启动(Windows Git Bash 可跑):后台拉起两个服务并探活,日志落 `logs/uvicorn.log`、`logs/spring.log`。

```bash
./start-all
# 成功后打印:Web: http://localhost:8080/practice | AI: http://localhost:8000
```

首次运行需先 `pip install -r requirements.txt`(含 fastapi/uvicorn),并让 Maven 拉取 Web 层依赖。也可手动分别启动:

```bash
python -m uvicorn interview_agent.server:app --port 8000   # AI 服务(前台)
mvn -f web spring-boot:run                                 # Web 服务(前台)
```

三个页面:

- **练习** `/practice`:选 topic 开刷 → 出题 → textarea 口述作答 → 「提交判题」出得分与点评;「下一题」换题(已问过的题号随请求排除,先轮换再重现);AI 服务不可用时页面顶部横幅提示,**作答文本不清空**,服务恢复后可直接重交。
- **统计** `/stats`:按 topic 查看答题数、平均分、未掌握错题数——与 CLI 退出时打印的统计同源(同一 SQL)。
- **问答** `/ask`:自由提问,RAG 检索题库后作答并附「接着练」推荐(需先跑过 `index`)。

`eval` 示例输出(2026-10-27 实跑,glm-4-flash,判题首轮已用 `tool_choice="required"` 强制工具调用):

```text
总案例: 60  命中: 4  命中率: 6.7%
no_record: 51  error: 0  平均分差: 0.211
分档统计:
  good     n=20  命中=1    命中率=5.0%
  partial  n=20  命中=3    命中率=15.0%
  bad      n=20  命中=0    命中率=0.0%
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
| P3 ✅ | 多 Agent 生成器-评估器(`scripts/generate_golden.py` 盲生成黄金集)+ Eval 黄金集(eval 子命令,存储隔离) |
| P4 ✅ | Web 界面:Spring Boot 页面层 + FastAPI AI 服务,双服务 `./start-all` 一键启动,与 CLI 同库同判题路径 |
| P5 | 判题 prompt 调优闭环(用 eval 度量调优前后)· 跨模型对比 eval(优先换更守 tool_choice 协议的模型/厂商) |

**Phase 3 结果:黄金集 60 案例档位命中 6.7%**(good 5.0% / partial 15.0% / bad 0.0%,no_record 51)——判题模型 glm-4-flash 在 eval 批量场景大量跳过 `record_result` 工具调用(harness 已试过 `tool_choice` 对象形式与 `"required"` 字符串形式两轮强制:quiz 真机冒烟生效,批量 eval 下该厂商均未稳定遵守,两轮 no_record 皆 51,已作为诚实基线接受)、且实际打分偏松(partial/bad 落工具的 5 例得 0.60~0.75 仅 3 例踩线命中)。这正是 eval 存在的意义:把「感觉判得还行」变成可度量的数字,P4 判题 prompt 调优与换更守协议的模型/厂商据此推进。

条件命中率(仅统计实际调用判分工具的案例): 4/9 = 44.4%

## 开发

```bash
pytest -q                   # Python 侧 70 个测试,无需真实 API key(全部 mock)
cd web && mvn -q test       # Web 侧 11 个测试(MockMvc + Mockito,不调真实 AI 服务)
```
