# 面试复习 Agent Phase 1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 一个 CLI 复习工具:Agent 出题 → 用户口述答案 → LLM 对照要点判分 → 落库 → 错题优先重现。

**Architecture:** 手写 ReAct 循环(OpenAI 兼容接口,默认 GLM),三个确定性工具(选题/落库/统计),SQLite 存储(表结构与 SQL 心智对齐 MySQL)。判题由主 Agent 承担,工具不含二次 LLM 调用。

**Tech Stack:** Python 3.13、httpx、sqlite3(标准库)、pytest、python-dotenv。

**Spec:** `docs/superpowers/specs/2026-10-14-interview-agent-design.md`

## Global Constraints

- Python 3.13;依赖仅 `httpx`、`python-dotenv`、`pytest`(dev)——不引入 LLM 官方 SDK、不引入 LangChain。
- 代码注释一律英文;面向用户的输出(题目/点评)中文。
- SQL 保持 MySQL 兼容心智,唯一 SQLite 方言例外:`datetime('now')`(迁移时替换为 `NOW()`)。
- `.env` 不入库;提供 `.env.example`。
- 每个 Task 结束必须 `pytest` 全绿 + git commit。

## Review Focus(执行时重点验证的输入类/失败模式)

1. **topic 不存在或题库为空** → `pick_question` 返回明确"无题"信息,不抛异常(Task 3 测试)。
2. **模型返回畸形 tool arguments(JSON 解析失败)** → 捕获后作为 error 回传模型自纠,不崩溃(Task 6 测试)。
3. **模型幻觉调用不存在的工具名** → registry 返回明确 error 回传(Task 6 测试)。
4. **score 越界(如 1.5 或 -1)** → record_result 内 clamp 到 [0,1](Task 4 测试)。
5. **单会话工具调用死循环** → 超过 max_tool_calls=20 强制终止并返回提示(Task 6 测试)。

---

### Task 1: 项目骨架 + 配置 + 数据库建表

**Files:**
- Create: `interview_agent/__init__.py`(空)
- Create: `interview_agent/config.py`
- Create: `interview_agent/store/__init__.py`(空)
- Create: `interview_agent/store/db.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `requirements.txt`
- Test: `tests/__init__.py`(空)、`tests/test_db.py`

**Interfaces:**
- Produces: `config.load_config(env_path=".env") -> config.Config`;`Config` 有 `base_url/api_key/model/db_path`(均 str)。
- Produces: `store.db.connect(db_path: str) -> sqlite3.Connection`;`init_schema(conn: sqlite3.Connection) -> None`(幂等,建 3 张表)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_db.py
import sqlite3
from interview_agent.store.db import connect, init_schema

def test_init_schema_creates_tables_idempotently():
    conn = connect(":memory:")
    init_schema(conn)
    tables = {r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"questions", "attempts", "wrong_notes"} <= tables
    init_schema(conn)  # idempotent
    assert True

def test_connect_sets_foreign_keys():
    conn = connect(":memory:")
    fk = conn.execute("PRAGMA foreign_keys").fetchone()[0]
    assert fk == 1
```

- [ ] **Step 2: 跑测试确认失败**
  Run: `pytest tests/test_db.py -v` → FAIL:`ModuleNotFoundError`

- [ ] **Step 3: 实现**

```python
# interview_agent/config.py
import os
from dataclasses import dataclass
from dotenv import load_dotenv

@dataclass
class Config:
    base_url: str
    api_key: str
    model: str
    db_path: str

def load_config(env_path: str = ".env") -> Config:
    """Load LLM and storage config from env file plus process env."""
    load_dotenv(env_path)
    return Config(
        base_url=os.environ["LLM_BASE_URL"],
        api_key=os.environ["LLM_API_KEY"],
        model=os.environ.get("LLM_MODEL", "glm-4-flash"),
        db_path=os.environ.get("DB_PATH", "interview.db"),
    )
```

```python
# interview_agent/store/db.py
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS questions (
  id INTEGER PRIMARY KEY,
  topic TEXT NOT NULL,
  difficulty INTEGER DEFAULT 2,
  question TEXT NOT NULL,
  answer_points TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  question_id INTEGER NOT NULL REFERENCES questions(id),
  user_answer TEXT NOT NULL,
  score REAL NOT NULL,
  feedback TEXT NOT NULL,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE TABLE IF NOT EXISTS wrong_notes (
  question_id INTEGER PRIMARY KEY REFERENCES questions(id),
  wrong_count INTEGER DEFAULT 1,
  streak_right INTEGER DEFAULT 0,
  mastered INTEGER DEFAULT 0,
  last_wrong_at TEXT
);
"""

def connect(db_path: str) -> sqlite3.Connection:
    """Open connection with foreign keys enabled."""
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_schema(conn: sqlite3.Connection) -> None:
    """Create tables if missing; safe to call repeatedly."""
    conn.executescript(SCHEMA)
```

```
# .env.example
LLM_BASE_URL=https://open.bigmodel.cn/api/paas/v4
LLM_API_KEY=sk-xxx
LLM_MODEL=glm-4-flash
DB_PATH=interview.db
```
`.gitignore`:`.env`、`__pycache__/`、`*.db`、`.pytest_cache/`
`requirements.txt`:`httpx`、`python-dotenv`;dev 段注释 `pytest`。

- [ ] **Step 4: 跑测试通过** Run: `pytest tests/test_db.py -v` → PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: skeleton, config, sqlite schema"`

---

### Task 2: 题库 repo + 种子数据导入

**Files:**
- Create: `interview_agent/store/questions.py`
- Create: `interview_agent/data/questions.json`
- Test: `tests/test_questions.py`

**Interfaces:**
- Consumes: `store.db.connect/init_schema`。
- Produces: `dataclasses.Question(id:int, topic:str, difficulty:int, question:str, answer_points:list[str])`;`QuestionRepo(conn)`,方法:`import_seed(json_path:str) -> int`(返回导入数,已导入则跳过)、`pick(topic:str, wrong_only:bool=False) -> Question | None`(优先级:wrong_notes 中 mastered=0 的最久未答 > 全局最久未答)、`get(question_id:int) -> Question | None`。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_questions.py
import json
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo

SEED = [
  {"id": 1, "topic": "jvm", "difficulty": 2, "question": "Q1",
   "answer_points": ["p1", "p2"]},
  {"id": 2, "topic": "mysql", "difficulty": 1, "question": "Q2",
   "answer_points": ["p1"]},
]

def make_repo(tmp_path):
    conn = connect(":memory:")
    init_schema(conn)
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps(SEED, ensure_ascii=False), encoding="utf-8")
    repo = QuestionRepo(conn)
    repo.import_seed(str(seed))
    return repo, conn

def test_import_seed_skips_duplicates(tmp_path):
    repo, _ = make_repo(tmp_path)
    assert repo.import_seed(str(tmp_path / "s.json")) == 0  # second run: 0 new

def test_pick_unknown_topic_returns_none(tmp_path):
    repo, _ = make_repo(tmp_path)
    assert repo.pick("nosuchtopic") is None      # Review Focus #1

def test_pick_prefers_wrong_notes(tmp_path):
    repo, conn = make_repo(tmp_path)
    # mark q1 as unmastered wrong note, most recent
    conn.execute("INSERT INTO wrong_notes(question_id, wrong_count, last_wrong_at)"
                 " VALUES (1, 1, datetime('now'))")
    assert repo.pick("mysql", wrong_only=False).id == 1  # wrong note wins over mysql's own
```

- [ ] **Step 2: 跑测试确认失败** Run: `pytest tests/test_questions.py -v` → FAIL
- [ ] **Step 3: 实现**

```python
# interview_agent/store/questions.py
import json
import sqlite3
from dataclasses import dataclass

@dataclass
class Question:
    id: int
    topic: str
    difficulty: int
    question: str
    answer_points: list[str]

class QuestionRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def import_seed(self, json_path: str) -> int:
        """Import seed questions; skip ids already present. Returns count."""
        with open(json_path, encoding="utf-8") as f:
            rows = json.load(f)
        existing = {r[0] for r in self.conn.execute("SELECT id FROM questions")}
        new = [r for r in rows if r["id"] not in existing]
        self.conn.executemany(
            "INSERT INTO questions(id, topic, difficulty, question, answer_points)"
            " VALUES (:id, :topic, :difficulty, :question, :answer_points_json)",
            [{**r, "answer_points_json": json.dumps(r["answer_points"], ensure_ascii=False)}
             for r in new])
        self.conn.commit()
        return len(new)

    def _row_to_q(self, row) -> Question:
        return Question(row[0], row[1], row[2], row[3], json.loads(row[4]))

    def get(self, question_id: int) -> Question | None:
        row = self.conn.execute(
            "SELECT id, topic, difficulty, question, answer_points"
            " FROM questions WHERE id=?", (question_id,)).fetchone()
        return self._row_to_q(row) if row else None

    def pick(self, topic: str, wrong_only: bool = False) -> Question | None:
        """Priority: unmastered wrong notes (oldest last_wrong_at first),
        then least-recently-attempted questions of the topic."""
        row = self.conn.execute(
            "SELECT q.id FROM questions q"
            " JOIN wrong_notes w ON w.question_id = q.id"
            " WHERE w.mastered = 0 ORDER BY w.last_wrong_at ASC LIMIT 1").fetchone()
        if row:
            return self.get(row[0])
        if wrong_only:
            return None
        row = self.conn.execute(
            "SELECT q.id FROM questions q"
            " LEFT JOIN attempts a ON a.question_id = q.id"
            " WHERE q.topic = ? GROUP BY q.id"
            " ORDER BY MAX(a.created_at) IS NULL DESC, MAX(a.created_at) ASC"
            " LIMIT 1", (topic,)).fetchone()
        return self.get(row[0]) if row else None
```

- [ ] **Step 4: 建种子题库 `interview_agent/data/questions.json`**

结构如下,**8 个 topic 各 8~10 题、共约 70 题**,题目与 `answer_points` 全部取自本学习会话已验证的沉淀(面经知识点、课程要点、历史错题)。每个 topic 至少包含对应历史错题。示例(执行时按同一结构扩满):

```json
[
 {"id": 1, "topic": "jvm", "difficulty": 2,
  "question": "JDK 8 为什么用元空间替代永久代?",
  "answer_points": ["永久代有固定上限且在 JVM 进程内", "动态生成类易撑爆 PermGen OOM", "元空间改用本地物理内存突破上限"]},
 {"id": 2, "topic": "jvm", "difficulty": 2,
  "question": "CMS 的浮动垃圾是什么?为什么导致必须预留空间?",
  "answer_points": ["并发清除期间用户线程新产生、本轮收不掉的垃圾", "需给浮动垃圾+晋升对象留余地", "余地不够触发 Concurrent Mode Failure", "退化 Serial Old 单线程标记整理 STW 长"]},
 {"id": 3, "topic": "agent", "difficulty": 2,
  "question": "工具调用中模型和代码各自做什么?",
  "answer_points": ["模型只输出 tool_use 申请单(工具名+参数)", "代码执行工具", "结果以 tool_result 回传模型", "模型不执行任何工具"]}
]
```
题目来源清单(执行时逐条落库):jvm=内存模型5区/元空间/GC Roots/三算法/CMS四阶段与优化/G1大稳懒/参数模板/浮动垃圾;thread_pool=7参数/执行流程/无界队列/拒绝策略/线程数公式;mysql=B+树三理由/回表覆盖索引/最左前缀/失效清单/EXPLAIN四列/物理序=主键;network=三次握手两次不行/TIME_WAIT/CLOSE_WAIT/雪崩击穿穿透/SYN Cookie;os=进程线程/死锁四条件/epoll;redis=去重三方案/三兄弟/持久化;netty_algo=Reactor主从/小顶堆守门员/海量TopK;agent=无状态与记忆本质/工具调用分工/embedding语义检索/RAG两流水线/多Agent上下文隔离/Eval黄金集。

- [ ] **Step 5: 跑测试通过** Run: `pytest tests/test_questions.py -v` → PASS
- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: question repo + seed bank (70q)"`

---

### Task 3: 答题落库 + 错题本状态机

**Files:**
- Create: `interview_agent/store/attempts.py`
- Test: `tests/test_attempts.py`

**Interfaces:**
- Consumes: Task 1 的 db;Task 2 的 QuestionRepo(构造测试数据)。
- Produces: `AttemptRepo(conn)`:`record(question_id:int, user_answer:str, score:float, feedback:str) -> None`(score 先 clamp 到 [0,1]);`stats(topic:str) -> dict`(键:`attempts/avg_score/wrong_count`);内部维护 wrong_notes 规则:score<0.6 → upsert(wrong_count+1, streak_right=0, last_wrong_at=now);score≥0.6 且已有记录 → streak_right+1,连 2 次置 mastered=1。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_attempts.py
import json
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo

def setup_repos(tmp_path, scores):
    conn = connect(":memory:")
    init_schema(conn)
    seed = tmp_path / "s.json"
    seed.write_text(json.dumps(
        [{"id": 1, "topic": "jvm", "difficulty": 2, "question": "Q",
          "answer_points": ["p"]}], ensure_ascii=False), encoding="utf-8")
    QuestionRepo(conn).import_seed(str(seed))
    repo = AttemptRepo(conn)
    for i, s in enumerate(scores):
        repo.record(1, f"ans{i}", s, "fb")
    return conn

def test_wrong_then_mastered_flow(tmp_path):
    conn = setup_repos(tmp_path, [0.2, 0.9, 0.9])
    w = conn.execute("SELECT wrong_count, streak_right, mastered FROM wrong_notes").fetchone()
    assert w == (1, 2, 1)  # one wrong, then 2-right streak => mastered

def test_score_clamped(tmp_path):
    conn = setup_repos(tmp_path, [1.5])
    s = conn.execute("SELECT score FROM attempts").fetchone()[0]
    assert s == 1.0        # Review Focus #4

def test_stats(tmp_path):
    conn = setup_repos(tmp_path, [0.2, 1.0])
    st = AttemptRepo(conn).stats("jvm")
    assert st == {"attempts": 2, "avg_score": 0.6, "wrong_count": 1}
```

- [ ] **Step 2: 跑测试确认失败** Run: `pytest tests/test_attempts.py -v` → FAIL
- [ ] **Step 3: 实现**

```python
# interview_agent/store/attempts.py
import sqlite3

class AttemptRepo:
    def __init__(self, conn: sqlite3.Connection):
        self.conn = conn

    def record(self, question_id: int, user_answer: str,
               score: float, feedback: str) -> None:
        """Persist an attempt and update the wrong-note state machine."""
        score = max(0.0, min(1.0, score))
        self.conn.execute(
            "INSERT INTO attempts(question_id, user_answer, score, feedback)"
            " VALUES (?,?,?,?)", (question_id, user_answer, score, feedback))
        if score < 0.6:
            self.conn.execute(
                "INSERT INTO wrong_notes(question_id, wrong_count, streak_right,"
                " mastered, last_wrong_at) VALUES (?,1,0,0,datetime('now'))"
                " ON CONFLICT(question_id) DO UPDATE SET"
                " wrong_count=wrong_count+1, streak_right=0, mastered=0,"
                " last_wrong_at=datetime('now')", (question_id,))
        else:
            self.conn.execute(
                "UPDATE wrong_notes SET streak_right=streak_right+1,"
                " mastered=CASE WHEN streak_right+1>=2 THEN 1 ELSE 0 END"
                " WHERE question_id=?", (question_id,))
        self.conn.commit()

    def stats(self, topic: str) -> dict:
        row = self.conn.execute(
            "SELECT COUNT(*), IFNULL(AVG(a.score),0) FROM attempts a"
            " JOIN questions q ON q.id=a.question_id WHERE q.topic=?",
            (topic,)).fetchone()
        wrong = self.conn.execute(
            "SELECT COUNT(*) FROM wrong_notes w JOIN questions q ON q.id=w.question_id"
            " WHERE q.topic=? AND w.mastered=0", (topic,)).fetchone()[0]
        return {"attempts": row[0], "avg_score": round(row[1], 2),
                "wrong_count": wrong}
```

- [ ] **Step 4: 跑测试通过** Run: `pytest tests/test_attempts.py -v` → PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: attempt repo + wrong-note state machine"`

---

### Task 4: LLM 客户端(httpx + 指数退避重试)

**Files:**
- Create: `interview_agent/llm/__init__.py`(空)、`interview_agent/llm/client.py`
- Test: `tests/test_llm_client.py`

**Interfaces:**
- Consumes: `config.Config`。
- Produces: `LLMClient(cfg: Config)`;`chat(messages: list[dict], tools: list[dict] | None = None) -> LLMResponse`;`LLMResponse(content: str, tool_calls: list[ToolCall], finish_reason: str)`;`ToolCall(id: str, name: str, arguments: dict)`。异常:`LLMConnectionError`(重试 3 次后)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_llm_client.py
import httpx, pytest
from interview_agent.config import Config
from interview_agent.llm.client import LLMClient, LLMConnectionError

CFG = Config("https://fake/v4", "sk-test", "m", ":memory:")

def test_chat_parses_tool_calls(monkeypatch):
    def fake_post(self, url, **kw):
        return httpx.Response(200, json={"choices": [{
            "finish_reason": "tool_calls",
            "message": {"content": "", "tool_calls": [{
                "id": "c1", "type": "function",
                "function": {"name": "pick_question",
                             "arguments": "{\"topic\": \"jvm\"}"}}]}}]})
    monkeypatch.setattr(httpx.Client, "post", fake_post)
    resp = LLMClient(CFG).chat([{"role": "user", "content": "hi"}])
    assert resp.finish_reason == "tool_calls"
    assert resp.tool_calls[0].arguments == {"topic": "jvm"}

def test_retry_then_fail(monkeypatch):
    calls = {"n": 0}
    def flaky(self, url, **kw):
        calls["n"] += 1
        raise httpx.ConnectError("boom")
    monkeypatch.setattr(httpx.Client, "post", flaky)
    monkeypatch.setattr("time.sleep", lambda s: None)
    with pytest.raises(LLMConnectionError):
        LLMClient(CFG).chat([{"role": "user", "content": "hi"}])
    assert calls["n"] == 3   # 1 + 2 retries
```

- [ ] **Step 2: 跑测试确认失败** Run: `pytest tests/test_llm_client.py -v` → FAIL
- [ ] **Step 3: 实现**

```python
# interview_agent/llm/client.py
import json, time
import httpx
from dataclasses import dataclass, field
from interview_agent.config import Config

@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict

@dataclass
class LLMResponse:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"

class LLMConnectionError(Exception):
    pass

class LLMClient:
    """Thin OpenAI-compatible chat client (works with GLM/DeepSeek/Kimi)."""
    def __init__(self, cfg: Config):
        self.cfg = cfg

    def chat(self, messages, tools=None) -> LLMResponse:
        body = {"model": self.cfg.model, "messages": messages}
        if tools:
            body["tools"] = tools
        last_err = None
        for attempt in range(3):  # exponential backoff: 1s, 2s, 4s
            try:
                with httpx.Client(timeout=60) as c:
                    r = c.post(f"{self.cfg.base_url}/chat/completions",
                               headers={"Authorization": f"Bearer {self.cfg.api_key}"},
                               json=body)
                r.raise_for_status()
                msg = r.json()["choices"][0]
                calls = [ToolCall(tc["id"], tc["function"]["name"],
                                  json.loads(tc["function"]["arguments"] or "{}"))
                         for tc in msg["message"].get("tool_calls") or []]
                return LLMResponse(msg["message"].get("content") or "",
                                   calls, msg.get("finish_reason", "stop"))
            except (httpx.HTTPError, KeyError, ValueError) as e:
                last_err = e
                time.sleep(2 ** attempt)
        raise LLMConnectionError(str(last_err))
```

- [ ] **Step 4: 跑测试通过** Run: `pytest tests/test_llm_client.py -v` → PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: openai-compatible llm client with retry"`

---

### Task 5: 工具注册表与三个工具

**Files:**
- Create: `interview_agent/tools/__init__.py`(空)、`interview_agent/tools/registry.py`、`interview_agent/tools/builtins.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: Task 2/3 的两个 repo。
- Produces: `ToolRegistry`:`register(schema: dict, handler: callable) -> None`、`schemas() -> list[dict]`、`execute(name: str, arguments: dict) -> str`(JSON 结果;未知工具名 → `{"error": "unknown tool ..."}`,handler 异常 → `{"error": ...}`,均不抛出);`build_default_registry(qrepo: QuestionRepo, arepo: AttemptRepo) -> ToolRegistry`(组装三个工具:`pick_question(topic, wrong_only=False)` 返回题面/ID/**不含 answer_points**;`record_result(question_id, score, feedback, user_answer)`;`get_stats(topic)`)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_tools.py
import json
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo
from interview_agent.tools.registry import ToolRegistry, build_default_registry

def make_reg():
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (1,'jvm',2,'Q1','[\"p1\"]')")
    conn.commit()
    return build_default_registry(QuestionRepo(conn), AttemptRepo(conn))

def test_pick_question_hides_answer_points():
    reg = make_reg()
    out = json.loads(reg.execute("pick_question", {"topic": "jvm"}))
    assert "answer_points" not in out and out["question_id"] == 1

def test_unknown_tool_returns_error_not_raise():
    reg = make_reg()
    out = json.loads(reg.execute("no_such", {}))
    assert "error" in out                # Review Focus #3

def test_record_result_flow():
    reg = make_reg()
    reg.execute("record_result", {"question_id": 1, "score": 0.3,
                                  "feedback": "f", "user_answer": "a"})
    stats = json.loads(reg.execute("get_stats", {"topic": "jvm"}))
    assert stats["wrong_count"] == 1

def test_schemas_shape():
    reg = make_reg()
    names = {t["function"]["name"] for t in reg.schemas()}
    assert names == {"pick_question", "record_result", "get_stats"}
```

- [ ] **Step 2: 跑测试确认失败** Run: `pytest tests/test_tools.py -v` → FAIL
- [ ] **Step 3: 实现**

```python
# interview_agent/tools/registry.py
import json, traceback

class ToolRegistry:
    """Map tool name -> (json-schema, handler). Never raises to the model."""
    def __init__(self):
        self._tools = {}

    def register(self, schema: dict, handler) -> None:
        self._tools[schema["function"]["name"]] = (schema, handler)

    def schemas(self) -> list[dict]:
        return [s for s, _ in self._tools.values()]

    def execute(self, name: str, arguments: dict) -> str:
        if name not in self._tools:
            return json.dumps({"error": f"unknown tool: {name}"}, ensure_ascii=False)
        try:
            return json.dumps(self._tools[name][1](**arguments),
                              ensure_ascii=False, default=str)
        except Exception:
            return json.dumps({"error": traceback.format_exc(limit=1)},
                              ensure_ascii=False)
```

```python
# interview_agent/tools/builtins.py
from .registry import ToolRegistry

def _f(name, desc, props, required, handler):
    return {"type": "function", "function": {
        "name": name, "description": desc,
        "parameters": {"type": "object", "properties": props,
                       "required": required}}}, handler

def build_default_registry(qrepo, arepo) -> ToolRegistry:
    reg = ToolRegistry()

    def pick_question(topic: str, wrong_only: bool = False) -> dict:
        q = qrepo.pick(topic, wrong_only)
        if q is None:
            return {"message": f"no question available for topic '{topic}'"}
        return {"question_id": q.id, "topic": q.topic,
                "difficulty": q.difficulty, "question": q.question}

    def record_result(question_id: int, score: float, feedback: str,
                      user_answer: str) -> dict:
        arepo.record(question_id, user_answer, score, feedback)
        return {"ok": True}

    def get_stats(topic: str) -> dict:
        return arepo.stats(topic)

    for schema, handler in [
        _f("pick_question", "Pick one interview question. Call at session start and"
           " whenever ready for the next question. Prefer wrong_only when the user"
           " asks to review mistakes.",
           {"topic": {"type": "string"},
            "wrong_only": {"type": "boolean"}}, ["topic"], pick_question),
        _f("record_result", "Persist grading of one user answer. score is 0~1"
           " hit-rate of answer points. Call exactly once per answered question.",
           {"question_id": {"type": "integer"}, "score": {"type": "number"},
            "feedback": {"type": "string"},
            "user_answer": {"type": "string"}},
           ["question_id", "score", "feedback", "user_answer"], record_result),
        _f("get_stats", "Get accuracy stats for a topic.",
           {"topic": {"type": "string"}}, ["topic"], get_stats),
    ]:
        reg.register(schema, handler)
    return reg
```

- [ ] **Step 4: 跑测试通过** Run: `pytest tests/test_tools.py -v` → PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: tool registry + 3 builtins"`

---

### Task 6: Agent 循环(状态机 + 安全阀)

**Files:**
- Create: `interview_agent/agent/__init__.py`(空)、`interview_agent/agent/loop.py`
- Test: `tests/test_loop.py`

**Interfaces:**
- Consumes: `LLMClient.chat`、`ToolRegistry`。
- Produces: `run_agent(client, registry, system: str, user_input: str,
  on_output=print, max_tool_calls: int = 20, messages: list[dict] | None = None) -> str`(返回最终文本;传入 messages 则在其上追加、复用会话历史,否则新建;工具结果以 `{"role":"tool","tool_call_id":...,"content":...}` 回填)。

- [ ] **Step 1: 写失败测试**

```python
# tests/test_loop.py
from interview_agent.agent.loop import run_agent

class FakeClient:
    """Scripted responses: tool call -> tool call(bad json name) -> final."""
    def __init__(self, script):
        self.script, self.seen = script, []
    def chat(self, messages, tools=None):
        self.seen.append([m["role"] for m in messages])
        return self.script.pop(0)

def resp_tool(call_id, name, args_json):
    from interview_agent.llm.client import LLMResponse, ToolCall
    return LLMResponse("", [ToolCall(call_id, name, args_json)], "tool_calls")

def resp_text(t):
    from interview_agent.llm.client import LLMResponse
    return LLMResponse(t, [], "stop")

def test_loop_executes_tool_and_feeds_back():
    client = FakeClient([
        resp_tool("c1", "pick_question", {"topic": "jvm"}),
        resp_text("here is your question")])
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): return '{"question_id": 1}'
    out = run_agent(client, Reg(), "sys", "start")
    assert out == "here is your question"
    assert client.seen[1][-1]["role"] == "tool"   # result fed back

def test_loop_bad_arguments_not_crash():
    class BoomArgs(str):  # arguments that json.loads already parsed -> we pass dict
        pass
    client = FakeClient([
        resp_tool("c1", "pick_question", {"no_topic": True}),  # wrong kwargs
        resp_text("recovered")])
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): raise TypeError("bad kwargs")
    out = run_agent(client, Reg(), "s", "u")     # Review Focus #2
    assert out == "recovered"                     # error fed back, no crash

def test_loop_stops_at_max_tool_calls():
    client = FakeClient([resp_tool("c", "pick_question", {"topic": "x"})] * 99)
    class Reg:
        def schemas(self): return []
        def execute(self, name, args): return '{"ok": 1}'
    out = run_agent(client, Reg(), "s", "u", max_tool_calls=3)  # Review Focus #5
    assert "too many" in out.lower()

def test_loop_reuses_session_messages():
    client = FakeClient([resp_text("ok")])
    shared = [{"role": "system", "content": "s"},
              {"role": "user", "content": "prev"}]
    run_agent(client, Reg(), "", "new", messages=shared)
    assert [m["content"] for m in shared] == ["s", "prev", "new"]
```

- [ ] **Step 2: 跑测试确认失败** Run: `pytest tests/test_loop.py -v` → FAIL
- [ ] **Step 3: 实现**

```python
# interview_agent/agent/loop.py
def run_agent(client, registry, system: str, user_input: str,
              on_output=print, max_tool_calls: int = 20,
              messages=None) -> str:
    """Hand-written ReAct loop: model fills the form, code executes, feed back.
    Pass an existing messages list to continue a session (extended in place)."""
    if messages is None:
        messages = [{"role": "system", "content": system},
                    {"role": "user", "content": user_input}]
    else:
        messages.append({"role": "user", "content": user_input})
    for _ in range(max_tool_calls):
        resp = client.chat(messages, registry.schemas())
        if not resp.tool_calls:
            on_output(resp.content)
            return resp.content
        messages.append({"role": "assistant", "content": resp.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.name,
                                                      "arguments": str(c.arguments)}}
                                        for c in resp.tool_calls]})
        for c in resp.tool_calls:
            result = registry.execute(c.name, c.arguments)
            messages.append({"role": "tool", "tool_call_id": c.id,
                             "content": result})
            on_output(f"[tool] {c.name} -> {result[:120]}")
    return "Stopped: too many tool calls in one session."
```

- [ ] **Step 4: 跑测试通过** Run: `pytest tests/test_loop.py -v` → PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: reAct loop with safety valve"`

---

### Task 7: CLI 入口 + system prompt + 端到端串联

**Files:**
- Create: `interview_agent/__main__.py`、`interview_agent/session.py`
- Test: `tests/test_session.py`(mock LLM 的会话级测试)

**Interfaces:**
- Consumes: 前面全部。
- Produces: `session.run_quiz(cfg, topic: str, wrong_only: bool) -> None`(交互主循环:每轮 `input()` 收答案 → 判题;Ctrl+C 优雅退出并打印 stats);`__main__.py` 的 argparse(`quiz` 子命令,`--topic`、`--wrong-only`)。system prompt 要点:角色=严格的技术面试官;流程=先 `pick_question` → 展示题目 → 收到用户答案后**对照 CLI 注入的 answer_points** 判分并调用 `record_result` → 点评(指出漏掉的要点)→ 继续下一题。

- [ ] **Step 1: 写失败测试(mock client 走完一轮 出题→判题→落库)**

```python
# tests/test_session.py
import json
from interview_agent.config import Config
from interview_agent.store.db import connect, init_schema
from interview_agent.store.questions import QuestionRepo
from interview_agent.store.attempts import AttemptRepo
from interview_agent.session import build_system_prompt, SessionDriver

def test_system_prompt_contains_rules():
    sp = build_system_prompt()
    assert "record_result" in sp and "answer_points" in sp

def test_session_driver_one_round():
    conn = connect(":memory:")
    init_schema(conn)
    conn.execute("INSERT INTO questions VALUES (1,'jvm',2,'Q?','[\"p\"]')")
    conn.commit()
    class FakeClient:
        def __init__(self): self.calls = 0
        def chat(self, messages, tools=None):
            from interview_agent.llm.client import LLMResponse, ToolCall
            self.calls += 1
            if self.calls == 1:  # grade(): model judges then records via tool
                return LLMResponse("", [ToolCall("c2", "record_result",
                                     {"question_id": 1, "score": 0.3,
                                      "feedback": "missed the point",
                                      "user_answer": "guessed"})], "tool_calls")
            return LLMResponse("点评:漏了要点", [], "stop")
    driver = SessionDriver(FakeClient(), QuestionRepo(conn), AttemptRepo(conn))
    driver.ask("jvm", wrong_only=False)   # direct tool call, no LLM involved
    driver.grade("my answer")             # run_agent: judge + record via tools
    stats = AttemptRepo(conn).stats("jvm")
    assert stats["attempts"] == 1 and stats["wrong_count"] == 1
```

- [ ] **Step 2: 跑测试确认失败** Run: `pytest tests/test_session.py -v` → FAIL
- [ ] **Step 3: 实现**

```python
# interview_agent/session.py
from .tools.registry import build_default_registry
from .agent.loop import run_agent

def build_system_prompt() -> str:
    return (
        "You are a strict technical interviewer for Java backend interviews."
        " Session flow: call pick_question to get a question and show it;"
        " after the user answers, you will receive the question's answer_points"
        " (grading rubric) injected as user message; grade strictly by point"
        " coverage, call record_result exactly once with score (0~1 = fraction"
        " of points hit) and concise Chinese feedback naming missed points,"
        " then continue with the next question. Judge in Chinese.")

class SessionDriver:
    """Two-phase driver: ask() picks+shows a question (direct tool call,
    no LLM); grade() injects rubric + user answer into run_agent so the
    model judges and records via tools. Session history lives in
    self.messages and is reused across grades."""
    def __init__(self, client, qrepo, arepo, max_tool_calls=6):
        self.client = client
        self.qrepo = qrepo
        self.arepo = arepo
        self.registry = build_default_registry(qrepo, arepo)
        self.messages = [{"role": "system", "content": build_system_prompt()}]
        self.max_tool_calls = max_tool_calls
        self.current = None

    def ask(self, topic: str, wrong_only: bool) -> None:
        import json
        out = json.loads(self.registry.execute(
            "pick_question", {"topic": topic, "wrong_only": wrong_only}))
        print(out)
        self.current = out

    def grade(self, user_answer: str) -> None:
        import json
        q = self.qrepo.get(self.current["question_id"])
        rubric_msg = ("Question: %s\nanswer_points(rubric): %s\nuser answer: %s"
                      % (q.question, json.dumps(q.answer_points, ensure_ascii=False),
                         user_answer))
        run_agent(self.client, self.registry, "", rubric_msg,
                  on_output=print,
                  max_tool_calls=self.max_tool_calls,
                  messages=self.messages)
```

实现说明(执行者注意):`SessionDriver.ask()` **不经过模型**直接调选题工具——选题是确定性动作,不该花一次 LLM 调用;判题才走模型(rubric 注入)。这与 spec 第 4 节"职责切分"一致。若你实现中发现 `grade()` 一次 chat 后模型只返回 record_result 而没给点评文本,**允许追加第二次 chat**(空 tools)拿点评——保持 messages 连续即可。

```python
# interview_agent/__main__.py
import argparse, sys
from .config import load_config
from .store.db import connect, init_schema
from .store.questions import QuestionRepo
from .store.attempts import AttemptRepo
from .llm.client import LLMClient
from .session import SessionDriver

def main():
    p = argparse.ArgumentParser(prog="interview_agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quiz")
    q.add_argument("--topic", required=True)
    q.add_argument("--wrong-only", action="store_true")
    args = p.parse_args()

    cfg = load_config()
    conn = connect(cfg.db_path)
    init_schema(conn)
    qrepo = QuestionRepo(conn)
    import os
    seed = os.path.join(os.path.dirname(__file__), "data", "questions.json")
    if os.path.exists(seed):
        qrepo.import_seed(seed)
    driver = SessionDriver(LLMClient(cfg), qrepo, AttemptRepo(conn))
    try:
        while True:
            driver.ask(args.topic, args.wrong_only)
            ans = input("你的回答(回车提交):\n> ")
            driver.grade(ans)
    except (KeyboardInterrupt, EOFError):
        print("\n本次统计:", AttemptRepo(conn).stats(args.topic))
        sys.exit(0)

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试通过 + 全量回归** Run: `pytest -v` → 全 PASS
- [ ] **Step 5: Commit** `git add -A && git commit -m "feat: cli session driver, wire end-to-end"`

---

### Task 8: README + 手工验收

**Files:**
- Create: `README.md`

- [ ] **Step 1: 写 README**(一页:项目定位、架构 ASCII 图、`pip install -r requirements.txt` + 复制 `.env.example` + `python -m interview_agent quiz --topic jvm` 三步上手、切换模型商说明、Phase 2~4 路线)。
- [ ] **Step 2: 手工冒烟(需真实 API key,由用户执行或授权执行)**:`python -m interview_agent quiz --topic jvm`,验证出题→作答→判分点评→`--wrong-only` 优先重现错题→Ctrl+C 出统计。
- [ ] **Step 3: 全量 `pytest -v` 绿 → `git add -A && git commit -m "docs: readme + phase 1 done"`**

---

## Self-Review 结果

1. **Spec 覆盖**:spec §3 范围(Task 7 CLI+seed)、§4 架构(T1~T7)、§5.1~5.3(T4/T5/T6)、§6 数据模型(T1/T2/T3)、§7 错误处理(T4 重试、T5 不吞错、Task 7 Ctrl+C)、§8 测试(各任务内)、§9 DoD(Task 8)——全覆盖。
2. **占位符扫描**:无 TBD/TODO;种子题库 Task 2 Step 4 给出完整结构+样例+逐模块来源清单(数据类任务,非逻辑占位)。
3. **类型一致性**:`QuestionRepo.pick/get`、`AttemptRepo.record/stats`、`LLMClient.chat→LLMResponse/ToolCall`、`ToolRegistry.execute/schemas`、`run_agent` 签名在各任务间一致;Task 7 `SessionDriver` 消费同一批接口。
4. **Review Focus**:5 条各有归属测试(标注在测试内注释)。
