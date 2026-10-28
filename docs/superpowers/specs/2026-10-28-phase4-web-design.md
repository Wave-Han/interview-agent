# Interview Agent Phase 4(Web 界面:Java 网关 + Python AI 服务)— 设计文档

- 日期:2026-10-28
- 状态:四节设计已与用户逐节确认
- 前置:Phase 1~3 已完成(62 测试,https://github.com/Wave-Han/interview-agent)

## 1. 背景与目标

CLI 已具备 刷题/RAG 问答/Eval 三大能力。Phase 4 交付 **Web 界面**,采用**双服务架构**:

- **Spring Boot Web 层**(Java 17,校招本命栈):页面渲染、会话编排、统计聚合;
- **FastAPI AI 服务**(Python):薄 HTTP 适配层,直接 import 现有 `interview_agent` 模块,零业务逻辑重写。

成功标准:浏览器完成核心练习循环(出题→答题→点评→错题入本,与 CLI 共用同一 SQLite 库);Java+Python 双栈进入简历叙事;CLI 双入口保留。

## 2. 已确认决策

| 决策项 | 选择 |
|--------|------|
| 架构 | Java 网关 + Python AI 服务(双进程,HTTP 互联) |
| Web 框架 | Spring Boot 3.x + Thymeleaf(无前端框架,原生 fetch) |
| Python 服务 | FastAPI + uvicorn(白名单扩项:fastapi、uvicorn) |
| 仓库形态 | 同 repo:`web/`(Maven 模块)+ Python 根;启动脚本拉起双进程 |
| 后置 | 判题 prompt 调优闭环、跨模型对比 eval → Phase 5(独立迭代) |

## 3. 进程拓扑

```
浏览器 ── HTTP ──> Spring Boot (localhost:8080)
                    │ Thymeleaf 页面、/web/grade 聚合、RestClient
                    └── HTTP ──> FastAPI (localhost:8000, interview_agent/server.py)
```
- `start-all` 脚本(Windows bash)后台拉起 uvicorn 与 mvn spring-boot:run;README 说明手动方式;
- docker-compose 可选,不作为交付要求。

## 4. Python 侧:`interview_agent/server.py`(薄适配)

| 端点 | 方法 | 请求 | 响应 | 复用 |
|------|------|------|------|------|
| `/api/question` | GET | `?topic=&wrong_only=&exclude_ids=1,2` | `{question_id, topic, difficulty, question}` 或 `{message}` | QuestionRepo.pick |
| `/api/grade` | POST | `{question_id, answer}` | `{score, feedback, recorded}`;未落库时 `{recorded: false, message: "判题未完成(模型未调用判分工具)"}` | 判题核(rubric+run_agent+tool_choice 强制+陈旧点评守卫) |
| `/api/ask` | POST | `{query}` | `{answer, recommend_question_id}` 或 `{message}`(索引空) | run_ask |
| `/api/stats` | GET | `?topic=` | `{attempts, avg_score, wrong_count}` | AttemptRepo.stats |

- 启动时 `load_config` + `connect/init_schema` + 种子导入(与 CLI 相同);**grade 走与 CLI 完全一致的判题路径**(共用 build_rubric_message/run_agent/force_first_tool);
- 异常映射:LLMAPIError/LLMConnectionError → HTTP 502 + 中文 message;其余 500 + 中文;`.env` 语义不变;
- CLI 子命令原样保留(双入口同一核心)。

## 5. Java 侧:`web/`(Spring Boot)

```
web/src/main/
├─ java/com/wavehan/agentweb/
│  ├─ AgentWebApplication.java
│  ├─ controller/WebController.java        # GET /practice /stats /ask;POST /web/grade
│  ├─ service/AiClientService.java         # RestClient → Python 4 端点;base-url 可配置
│  └─ dto/ QuestionDto/GradeResultDto/StatsDto/AskResultDto(record)
└─ resources/
   ├─ application.yml                      # python-api.base-url: http://localhost:8000
   └─ templates/ practice.html stats.html ask.html
```
- **practice 页**:topic 下拉(8 topic)→ 出题卡 → 答题文本框 → fetch `/web/grade` → 点评卡(score+feedback)→ "下一题"按钮循环;错题自动入本(由 Python grade 落库);
- **stats 页**:topic 表格(答题数/平均分/未掌握错题);
- **ask 页**:输入框 → 讲解 + 💡推荐题;
- 页面原生 JS fetch,无前端框架;`/` 重定向 `/practice`;
- Python 不可达 → 统一 `{error: "AI 服务不可用,请先启动 Python 服务"}`,页面提示条,不白屏;判分跳过 → 显示与 CLI 相同语义的 ⚠️ 提示(`recorded:false`)。

## 6. 错误处理汇总

- Python 端点:LLM 异常 → 502+中文;索引空/无题 → 200+`message` 字段(语义信息,非错误);
- Java:RestClient 调用全包 try/catch → 友好 JSON;不向上抛 500;
- 浏览器侧:fetch 失败 → 提示条,页面状态保留(答案不丢)。

## 7. 测试

- Python(+~7,共 ~69):FastAPI TestClient + monkeypatch LLMClient——question 默认/排除、grade 落库与 recorded:false 路径、ask 索引空、stats;现有 62 测试原样绿;
- Java:`mvn test`——JUnit5+Mockito:AiClientService(mock RestClient)聚合逻辑、WebController 路由映射与错误分支;不引 WireMock;
- 两套独立运行;真实浏览器冒烟人工执行(启动双服务走完 practice/stats/ask)。

## 8. 顺手零碎(终审遗留)

1. `scripts/generate_golden.py` BAND_SPECS good 档措辞:"要点"→"内容"(与其余档一致);
2. 生成器 `--ids` 非数字项 → 中文 SystemExit 报错,不裸 traceback。

## 9. 验收标准(DoD)

1. 浏览器完成 出题→答题→点评→下一题 全循环;错题入本且 CLI 可见(同一 interview.db);
2. stats 数字 = CLI get_stats;ask 页可用;
3. Python 停服时 Web 显示友好错误,Spring 不崩;重启后恢复;
4. `pytest`(~69)与 `mvn test` 双绿;
5. README/CLAUDE.md:双服务架构图、启动说明、依赖更新、Phase 5 待办(调优闭环+跨模型);
6. 流程:writing-plans → SDD(实现→逐任务评审→终审);真实冒烟人工。

## 10. 明确不做(Phase 5+)

判题 prompt 调优闭环、跨模型对比、用户系统/多用户、HTTPS/部署上线、前端框架化、WebSocket 流式输出。
