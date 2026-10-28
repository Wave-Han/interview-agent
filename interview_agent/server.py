# interview_agent/server.py
# FastAPI AI service: a thin HTTP adapter over the existing core modules
# (same grading path as the CLI: rubric message -> run_agent with forced
# record_result -> attempt-id guard). Stateless per request; shares the
# same SQLite database as the CLI.
import os
import re
import sqlite3
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from .agent.loop import run_agent
from .config import load_config
from .llm.client import LLMClient, LLMAPIError, LLMConnectionError
from .rag.qa import run_ask, IndexEmptyError
from .session import build_system_prompt, build_rubric_message
from .store.attempts import AttemptRepo
from .store.db import init_schema
from .store.questions import QuestionRepo
from .store.vectors import VectorRepo
from .tools.registry import build_default_registry

# run_ask's system prompt has the model end with a "💡 接着练:" line that
# echoes the recommended question id; run_ask itself returns text only, so
# the id is recovered from that line for the JSON contract.
_RECOMMEND_RE = re.compile(r"接着练[:：][^\d]*(\d+)")


def make_client(cfg):
    """Single construction point for the LLM client (tests monkeypatch this)."""
    return LLMClient(cfg)


class _RecordOnceRepo:
    """Per-request AttemptRepo proxy for the grade endpoint.

    run_agent's safety valve lets a degenerate provider repeat the
    record_result tool for up to max_tool_calls rounds; the tool contract
    is exactly-once-per-turn, so the HTTP service keeps ONE attempt per
    request and later duplicate tool rounds become no-ops. Everything
    except record() delegates untouched."""

    def __init__(self, inner: AttemptRepo):
        self._inner = inner
        self._recorded = False

    def record(self, question_id, user_answer, score, feedback) -> None:
        if self._recorded:
            return
        self._recorded = True
        self._inner.record(question_id, user_answer, score, feedback)

    def max_attempt_id(self, question_id):
        return self._inner.max_attempt_id(question_id)

    def latest_feedback(self, question_id):
        return self._inner.latest_feedback(question_id)

    def stats(self, topic):
        return self._inner.stats(topic)


class GradeRequest(BaseModel):
    question_id: int
    answer: str


class AskRequest(BaseModel):
    query: str


def create_app(cfg, conn) -> FastAPI:
    """Assemble the FastAPI app over explicit cfg/conn.

    Tests pass an in-memory conn and a monkeypatched make_client; the
    uvicorn entrypoint passes None/None and lifespan bootstraps lazily
    (load_config -> connect -> init_schema -> import_seed), so importing
    this module never touches .env or a file database."""

    @asynccontextmanager
    async def _lifespan(_app: FastAPI):
        # Lazy bootstrap for the uvicorn path only; the test path passes
        # an explicit conn and never enters this branch.
        if _app.state.conn is None:
            boot_cfg = load_config()
            # Open the server-owned connection directly instead of via
            # store.db.connect: FastAPI runs sync endpoints on threadpool
            # worker threads (not the lifespan/event-loop thread), so the
            # connection must be thread-flexible or every request raises
            # sqlite3.ProgrammingError. PRAGMA mirrors connect()'s behavior;
            # sqlite's serialized mode makes cross-worker use safe.
            boot_conn = sqlite3.connect(boot_cfg.db_path,
                                        check_same_thread=False)
            boot_conn.execute("PRAGMA foreign_keys = ON")
            init_schema(boot_conn)
            seed = os.path.join(os.path.dirname(__file__), "data",
                                "questions.json")
            if os.path.exists(seed):
                QuestionRepo(boot_conn).import_seed(seed)
            _app.state.cfg = boot_cfg
            _app.state.conn = boot_conn
        yield

    app = FastAPI(lifespan=_lifespan)
    app.state.cfg = cfg
    app.state.conn = conn

    @app.get("/api/question")
    def question(topic: str, wrong_only: bool = False,
                 exclude_ids: str = ""):
        conn = app.state.conn
        try:
            exclude = [int(x) for x in exclude_ids.split(",") if x.strip()]
        except ValueError:
            raise HTTPException(
                400, "exclude_ids 格式错误,应为逗号分隔的题号,如 1,2")
        q = QuestionRepo(conn).pick(topic, wrong_only, exclude_ids=exclude)
        # pick relaxes the exclusion when everything else is exhausted (the
        # CLI's resurfacing policy); the HTTP contract is strict — an
        # excluded id must not come back, the caller relaxes by resending
        # a shorter exclude list. Cross-topic wrong-note resurfacing (pick's
        # global wrong-first policy) still passes through.
        if q is None or q.id in exclude:
            return {"message": f"no question available for topic '{topic}'"}
        return {"question_id": q.id, "topic": q.topic,
                "difficulty": q.difficulty, "question": q.question}

    @app.post("/api/grade")
    def grade(req: GradeRequest):
        conn = app.state.conn
        qrepo = QuestionRepo(conn)
        arepo = AttemptRepo(conn)
        q = qrepo.get(req.question_id)
        if q is None:
            raise HTTPException(404, f"题目不存在: {req.question_id}")
        prev = arepo.max_attempt_id(req.question_id) or 0
        # Per-request local message list: the HTTP service keeps no session
        # history across requests (unlike the CLI driver).
        messages = [{"role": "system", "content": build_system_prompt()}]
        registry = build_default_registry(qrepo, _RecordOnceRepo(arepo))
        try:
            run_agent(make_client(app.state.cfg), registry, "",
                      build_rubric_message(q, req.answer),
                      on_output=lambda s: None, max_tool_calls=6,
                      force_first_tool="record_result", messages=messages)
        except LLMAPIError as e:
            raise HTTPException(
                502, f"LLM 接口错误(状态码 {e.status_code}),请检查 .env 配置")
        except LLMConnectionError:
            raise HTTPException(502, "LLM 连接失败,请检查网络与 .env 配置")
        new_max = arepo.max_attempt_id(req.question_id) or 0
        if new_max <= prev:
            return {"recorded": False,
                    "message": "判题未完成(模型未调用判分工具)"}
        score = conn.execute("SELECT score FROM attempts WHERE id=?",
                             (new_max,)).fetchone()[0]
        return {"score": score, "feedback": arepo.latest_feedback(req.question_id),
                "recorded": True}

    @app.post("/api/ask")
    def ask(req: AskRequest):
        conn = app.state.conn
        wrong_ids = {row[0] for row in conn.execute(
            "SELECT question_id FROM wrong_notes WHERE mastered=0")}
        try:
            answer = run_ask(make_client(app.state.cfg), QuestionRepo(conn),
                             wrong_ids, VectorRepo(conn), req.query)
        except IndexEmptyError:
            return {"message": "向量索引为空,请先运行: python -m interview_agent index"}
        except LLMAPIError as e:
            raise HTTPException(
                502, f"LLM 接口错误(状态码 {e.status_code}),请检查 .env 配置")
        except LLMConnectionError:
            raise HTTPException(502, "LLM 连接失败,请检查网络与 .env 配置")
        out = {"answer": answer}
        m = _RECOMMEND_RE.search(answer)
        if m:
            out["recommend_question_id"] = int(m.group(1))
        return out

    @app.get("/api/stats")
    def stats(topic: str):
        # Delegate to AttemptRepo.stats so the numbers are CLI-identical
        # (get_stats tool and `python -m interview_agent quiz` print this
        # same query's results).
        return AttemptRepo(app.state.conn).stats(topic)

    return app


# Module-level app for `uvicorn interview_agent.server:app`; cfg/conn are
# bootstrapped lazily in lifespan so importing this module stays side-effect
# free (the test path passes an explicit conn to create_app instead).
app = create_app(None, None)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)
