# interview-agent

面试复习 Agent:CLI 出题 → 用户口述答案 → LLM 对照评分要点(rubric)判分落库 → 错题优先重现。Phase 4(Web 界面:Spring Boot 页面层 + FastAPI AI 服务)已完成,仓库:https://github.com/Wave-Han/interview-agent

## 常用命令

```bash
python -m pytest -q                                     # Python 侧全量测试(70 个)
cd web && mvn -q test                                   # Web 侧测试(11 个)
./start-all                                             # 一键双服务:FastAPI 8000 + Spring Boot 8080,探活后打印入口地址
python -m uvicorn interview_agent.server:app --port 8000 # 手动启动 AI 服务(start-all 的备选)
mvn -f web spring-boot:run                              # 手动启动 Web 服务(start-all 的备选)
python -m interview_agent quiz --topic jvm              # 开练(topic: jvm/thread_pool/mysql/network/os/redis/netty_algo/agent)
python -m interview_agent quiz --topic jvm --wrong-only # 只打错题
python -m interview_agent quiz --topic jvm --resume     # 恢复上次会话(按 topic 存取)
python -m interview_agent index                         # 建/重建向量索引(改题后必须重跑)
python -m interview_agent ask "为什么三次握手不能两次"    # RAG 问答(需先跑过 index)
python -m interview_agent eval                          # 黄金集 eval:60 案例真实 API 判题,报告落盘 docs/eval/
```

## 架构速览

| 模块 | 职责 |
|------|------|
| `interview_agent/__main__.py` | CLI 入口(quiz/index/ask 子命令、错误分流、Ctrl+C 统计、save_with_fallback 中途换库) |
| `interview_agent/session.py` | SessionDriver:ask() 直连选题工具(不走 LLM);grade() 注入 rubric 进 run_agent 判题 |
| `interview_agent/agent/loop.py` | 手写 ReAct 循环(tool_calls → 执行 → tool_result 回填;20 次安全阀) |
| `interview_agent/llm/client.py` | OpenAI 兼容薄抽象(httpx 直连,不用官方 SDK),chat + embed 双通道,指数退避 ×3 |
| `interview_agent/tools/` | pick_question / record_result / get_stats;registry.execute 永不抛异常 |
| `interview_agent/store/` | SQLite 五表(questions/attempts/wrong_notes/question_vectors/sessions);错题状态机:连对 2 次 → mastered |
| `interview_agent/rag/` | 手写 cosine 检索(retriever)+ ask 子命令固定管线(qa,含 IndexEmpty 守卫) |
| `interview_agent/eval/` | 生成器-评估器:黄金集 20 题 × 3 档逐案例过真实判题 ReAct 循环;EvalRecorder 内存接收 record_result(存储隔离,eval 永不写学习表);表格打印 + 报告落盘 docs/eval/ |
| `interview_agent/session_store.py` | SessionStore 协议三实现(memory/SQLite/Redis),工厂探测 REDIS_URL,不可用自动降级 SQLite |
| `interview_agent/server.py` | FastAPI 薄适配:4 端点(question/grade/ask/stats),grade 与 CLI 同判题路径(rubric 消息 + 强制 record_result + attempt-id 守卫) |
| `web/` | Spring Boot 页面层(8080):三页面(practice/stats/ask)+ `/web/*` 聚合端点,AiClientService 转发 FastAPI 并降级为 error JSON |

## 硬性约定(改代码前必读)

- **模型填表,代码干活**:判题的 question_id 必须在 rubric 消息首行显式给模型;展示给用户的点评一律取自 DB 的 feedback(latest_feedback),不信模型自由文本(历史教训:模型会幻演判题消息模板)。
- **SQL 零方言**:不用 ON CONFLICT / AUTOINCREMENT 之外的 SQLite 特性;错题状态机计算在 Python 侧(MySQL 的 SET 从左到右求值,SQL 侧自增列会改变语义)。唯一豁免:`datetime('now')`。
- **向量 float32 LE BLOB,零 numpy**(struct.pack/unpack 序列化);**改题后必须重跑 `index`**,否则检索命中的是旧向量。
- 注释英文;面向用户的输出中文。
- 依赖白名单:httpx、python-dotenv、redis(可选运行时,未装/未配置自动降级 SQLite)、fastapi、uvicorn、pytest(dev)。禁止引入 LLM 官方 SDK / LangChain / numpy。
- Java→Python HTTP 调用必须强制 HTTP/1.1 且 JVM UTF-8(AiClientService 构造器 + pom jvmArguments):JDK HttpClient 默认 h2c upgrade 会让 uvicorn body 解析炸 422;Windows JVM 默认 GBK 会把中文 body 发成 GBK 字节。
- 用户答案一律用 `=== USER ANSWER START/END ===` 定界 + prompt 声明 untrusted(防注入操纵判分)。
- 选题策略:未掌握错题全局优先(刻意设计)、本会话已问排除(exclude_ids,"稍后再见"非"立刻重考")。

## 流程

- 小改动:直接改 + pytest 绿 + commit,不进 plan。
- 新特性:先 brainstorming 出 spec(`docs/superpowers/specs/`),大特性走 subagent-driven-development(历史 spec/plan 在 `docs/superpowers/` 有完整留痕)。
- 真实 LLM 行为改动必须真实 API 冒烟——mock 验证逻辑,冒烟验证行为(两个生产 bug 都是冒烟抓的)。

## Phase 5 待办

判题 prompt 调优闭环(用 eval 度量调优前后;2026-10-27 基线:黄金集 60 案例档位命中 6.7%,good 5.0%/partial 15.0%/bad 0.0%,no_record 51——tool_choice 对象形式与 "required" 字符串形式两轮强制均未压下该厂商批量场景的随机跳过,已作诚实基线接受;打分偏松,partial/bad 落工具的 5 例 0.60~0.75)· 跨模型对比 eval(优先换更守 tool_choice 协议的模型/厂商)· conftest 线程 shim 恢复评估 · askedIds 按 topic 隔离
