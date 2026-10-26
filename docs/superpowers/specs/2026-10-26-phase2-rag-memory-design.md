# Interview Agent Phase 2(RAG 问答 + 会话存储)— 设计文档

- 日期:2026-10-26
- 状态:六节设计已与用户逐节确认
- 前置:Phase 1 已上线(https://github.com/Wave-Han/interview-agent,本地 `D:\develop-project\personal-ai-project\interview-agent`)

## 1. 背景与目标

Phase 1 实现了被动刷题(出题→判分→错题优先)。Phase 2 升级为:

1. **主动提问(RAG)**:`ask` 子命令——自由提问,基于题库语义检索生成讲解并推荐相关练习题;
2. **会话可恢复(记忆)**:quiz 会话持久化到可插拔存储(内存/SQLite/Redis),`--resume` 恢复上下文;
3. **fix-later 全清**:Phase 1 终审遗留的 4 项技术债。

成功标准:备考时既能被动刷题也能主动问;中断的练习可恢复;Redis 缺席时全功能可用。

## 2. 已确认决策

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 范围 | A+B+C 全上(RAG+Redis+fix-later) | 用户明确选择完整版 |
| embedding | 智谱 embedding API(OpenAI 兼容 `/embeddings`) | 复用现有 key;建库一次性几分钱;本机 AMD 无 CUDA,本地模型不友好 |
| 向量检索 | **手写 cosine 暴力扫**(向量存 SQLite BLOB,struct 打包,不引 numpy) | 70 题规模微秒级;与"手写 agent loop"同哲学;万级再上 ANN |
| 架构 | `ask` 固定管线(embed→检索→注入→单次 chat,无 tools) | 检索是确定性步骤,"廉价规则前置,昂贵模型后置";quiz 流程零改动 |
| 会话存储 | SessionStore 抽象,三实现;Redis 探测失败自动降级 SQLite | 不装 Redis 也全功能可用 |

## 3. 用户可见变化

```bash
python -m interview_agent ask "为什么三次握手不能两次"   # RAG 问答
python -m interview_agent index                          # 建向量索引(幂等,改题后重跑)
python -m interview_agent quiz --topic jvm --resume      # 恢复上次该 topic 会话
```

- `ask` 输出:中文讲解(基于检索到的题目与评分要点)+ 末尾推荐 1 道相关练习题(未掌握错题优先,附题号);
- Redis 不可用:启动一行提示 + 降级 SQLite,不报错;
- 索引为空时 `ask` 中文提示先运行 `index`。

## 4. 架构

### 4.1 RAG 管线

```
离线 index:questions 全量 → text = 题面 + " " + 要点拼接
          → LLMClient.embed(texts) 批量一次调用 → float32 bytes 存 question_vectors

在线 ask:  query → embed(单条) → 载入全部向量内存
          → cosine 排序 top-3 → 资料+题目注入 prompt
          → 单次 chat(无 tools) → 讲解 + 推荐题(未 mastered 优先)
```

- 新表:`question_vectors(question_id INTEGER PRIMARY KEY REFERENCES questions(id), dim INTEGER NOT NULL, vec BLOB NOT NULL)`;BLOB = float32 little-endian 数组(`struct.pack(f"<{n}f", *vec)`);
- `store/questions.py` 增向量读写:`upsert_vectors(rows)`(事务内 DELETE 全部+批量 INSERT,幂等重建)、`all_vectors() -> list[tuple[int, list[float]]]`;
- 新模块 `rag/retriever.py`:`cosine(a, b) -> float`、`top_k(query_vec, candidates, k) -> list[tuple[int, float]]`;
- `llm/client.py` 增 `embed(texts: list[str]) -> list[list[float]]`(POST `/embeddings`,model 取 `EMBEDDING_MODEL` 默认 `embedding-3`,复用重试);
- `ask` 组装 prompt:角色=耐心的中文讲师;资料=每题"题#id [topic]:题面;要点:…"各一段;要求=基于资料讲解,若资料不含答案如实说明;末尾从资料题中推荐 1 道最相关且未掌握的题,格式"💡 接着练:题 #id 题面"。

### 4.2 SessionStore

```python
# interview_agent/session_store.py
class SessionStore(Protocol):
    def save(self, session_id: str, messages: list[dict]) -> None: ...
    def load(self, session_id: str) -> list[dict] | None: ...
    def touch(self, session_id: str) -> None: ...
```

| 实现 | 细节 |
|------|------|
| `MemorySessionStore` | 进程内 dict;测试与默认回退 |
| `SqliteSessionStore` | 表 `sessions(id TEXT PRIMARY KEY, messages TEXT NOT NULL, updated_at TEXT NOT NULL DEFAULT (datetime('now')))`;应用层过期:构造时 DELETE updated_at < 7 天前 |
| `RedisSessionStore` | redis-py;key `ia:session:{id}` = JSON messages;`SET ... EX 86400`;save/touch 均 EXPIRE 刷新(**滑动过期**) |

- 工厂 `make_session_store(cfg) -> tuple[SessionStore, str]`(返回实现+使用的后端名):`REDIS_URL` 已配置 → `Redis.ping(socket_timeout=0.5)` 成功 → Redis;失败/未配置 → 一行提示 `Redis 不可用,会话将存 SQLite` → SqliteSessionStore;
- 集成:`session_id = topic`;`__main__` 每轮 grade 后 `store.save(topic, driver.messages)`;Ctrl+C/LLMConnectionError 退出前 save;`--resume` 且 `load()` 非 None → 构造 driver 后替换 `driver.messages`(保留原 system);
- `.env.example` 增:`EMBEDDING_MODEL=embedding-3`、`REDIS_URL=redis://localhost:6379/0`(注释标明可选)。

### 4.3 fix-later 清理(同一 Phase 内完成)

1. **重试语义**(`llm/client.py`):sleep 仅当 `attempt < 2`;捕获 `httpx.HTTPStatusError` 且 `400<=status<500` 且 `!=429` → 不重试,抛 `LLMAPIError`(新异常,携带状态码);`LLMConnectionError` 语义收窄为网络/5xx/超时;
2. **httpx Client 复用**:`LLMClient` 惰性创建并持有单个 `httpx.Client`(进程生命周期,不显式关闭);
3. **种子复合要点拆分**(q6/q40/q65/q70):answer_points 拆为单事实条目(纯数据修改;README 注明改题后须重跑 `index`);
4. **registry 异常路径测试**:`test_tools` 补"handler raise → execute 返回 `{"error": ...}`"直接用例。

## 5. 错误处理

- embedding 调用失败:复用 chat 的重试与 4xx 分类;
- `index` 中途失败:事务回滚(向量表要么全量重建要么不动);
- Redis 连接/操作异常:工厂降级一次;若会话中途 Redis 异常,save 捕获后降级提示并转存 SQLite(不崩会话);
- `ask` 索引为空:中文提示"向量索引为空,请先运行 python -m interview_agent index"。

## 6. 测试策略(22 → 约 38)

- `rag/retriever`:cosine 已知向量(正交=0、同向=1、反向=-1);top_k 排序与 k 截断;
- 向量编解码:struct pack/unpack 往返;`upsert_vectors` 幂等(重跑行数不变);
- `embed`:mock httpx(沿用 T4 假响应模式);
- SessionStore:**同一协议测试套件参数化跑三实现**(Sqlite/Memory 真跑;Redis 以 mock 打桩 redis-py 客户端,不起真服务、不引 fakeredis);Sqlite 过期清理用直接改 updated_at 模拟;
- `ask` 管线:fake embed + fake chat,断言 prompt 含资料与推荐题、空索引走提示分支;
- 重试语义:4xx 立即抛 `LLMAPIError` 且仅 1 次调用;末次失败后无 sleep;
- `--resume`:fake store 断言 save 调用点(每轮 grade 后)与 load 注入;
- 真实 API 冒烟(人工,交付时执行):`index` → `ask "为什么三次握手不能两次"` → `quiz --topic jvm --resume`。

## 7. 验收标准(DoD)

1. `index` 幂等;`ask` 输出含检索依据的讲解与推荐题;
2. quiz 中断后 `--resume` 恢复对话历史继续判题;
3. 无 Redis 环境全功能可用(含降级提示);
4. fix-later 4 项全清;`pytest` 全绿(约 38);
5. README 与项目 CLAUDE.md 同步(新命令、可选 Redis、依赖:新增 `redis`);
6. 流程:writing-plans → subagent 驱动(实现→逐任务评审→整分支终审→真实冒烟)。

## 8. 明确不做(Phase 3+)

多 Agent(出题者/判题者分离)、Eval 黄金集、Web 界面、ANN 向量索引、embedding 本地模型、记忆摘要压缩。
