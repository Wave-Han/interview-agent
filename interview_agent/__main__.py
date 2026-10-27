# interview_agent/__main__.py
# CLI entry: argparse subcommands (quiz/index/ask/eval) + interactive loop +
# graceful exit with session persistence and mid-session store fallback.
import argparse
import json
import os
import re
import sys
from datetime import date

from .config import load_config
from .store.db import connect, init_schema
from .store.questions import QuestionRepo
from .store.attempts import AttemptRepo
from .store.vectors import VectorRepo
from .llm.client import LLMClient, LLMConnectionError, LLMAPIError
from .session import SessionDriver
from .session_store import make_session_store, SqliteSessionStore
from .rag.qa import run_ask, IndexEmptyError
from .eval.runner import validate_golden, run_eval


def save_with_fallback(store, conn, topic: str, messages: list[dict]):
    """Persist the session; on backend failure swap to SQLite and re-save.

    A store that dies mid-session (e.g. Redis restart) must not lose the
    conversation: catch the exception, print one Chinese line, replace the
    store with a SqliteSessionStore that has the messages re-saved, and
    return it so the caller keeps using the working backend. If the SQLite
    fallback dies too, print instead of raising so the session can still
    end gracefully.
    """
    try:
        store.save(topic, messages)
        return store
    except Exception:
        print("会话存储异常,已切换到本地 SQLite 保存")
        fallback = SqliteSessionStore(conn)
        try:
            fallback.save(topic, messages)
        except Exception:
            print("本地保存也失败,本次会话记录未能持久化")
        return fallback


def rebuild_asked(messages: list[dict]) -> set[int]:
    """Rebuild the asked-question id set from a restored session's messages.

    Every grading turn's user message starts with a 'question_id: N' rubric
    line, so scanning message contents with that pattern recovers what the
    driver already asked. Without this, --resume would leave asked empty and
    the global wrong-first policy could re-ask a just-answered question.
    """
    asked: set[int] = set()
    for m in messages:
        for line in (m.get("content") or "").splitlines():
            match = re.fullmatch(r"question_id: (\d+)", line)
            if match:
                asked.add(int(match.group(1)))
    return asked


def main():
    p = argparse.ArgumentParser(prog="interview_agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quiz")
    q.add_argument("--topic", required=True)
    q.add_argument("--wrong-only", action="store_true")
    q.add_argument("--resume", action="store_true")
    sub.add_parser("index")
    a = sub.add_parser("ask")
    a.add_argument("question")
    ev = sub.add_parser("eval")
    ev.add_argument("--sample", type=int, default=None,
                    help="随机抽取的案例数(默认全部)")
    args = p.parse_args()

    # load_config raises bare KeyError on a missing env key (parked from T1);
    # surface it as a readable Chinese message instead of a traceback.
    try:
        cfg = load_config()
    except KeyError as e:
        print(f"缺少配置项 {e.args[0]},请检查 .env 文件")
        sys.exit(1)

    conn = connect(cfg.db_path)
    init_schema(conn)
    qrepo = QuestionRepo(conn)
    seed = os.path.join(os.path.dirname(__file__), "data", "questions.json")
    if os.path.exists(seed):
        qrepo.import_seed(seed)

    if args.cmd == "index":
        # One text per question: question text + answer points joined by "; ".
        rows = conn.execute(
            "SELECT id, question, answer_points FROM questions").fetchall()
        texts = [row[1] + " " + "; ".join(json.loads(row[2]))
                 for row in rows]
        if not texts:  # empty bank: skip the embed call entirely
            print("已索引 0 题")
            return
        client = LLMClient(cfg)
        # Chunking at the provider's 64-item cap happens inside embed().
        try:
            vecs = client.embed(texts)
        except LLMAPIError as e:
            # 4xx from the API: same Chinese message as the ask branch
            # (f62a1e4); no stats print because index has no topic context.
            print(f"LLM 接口错误(状态码 {e.status_code}),请检查 .env 配置")
            sys.exit(1)
        except LLMConnectionError:
            # Network failure: mirror the ask/quiz branch message.
            print("LLM 连接失败,请检查网络与 .env 配置")
            sys.exit(1)
        n = VectorRepo(conn).rebuild(list(zip([r[0] for r in rows], vecs)))
        print(f"已索引 {n} 题")
        return

    if args.cmd == "ask":
        wrong_ids = {row[0] for row in conn.execute(
            "SELECT question_id FROM wrong_notes WHERE mastered=0")}
        try:
            answer = run_ask(LLMClient(cfg), qrepo, wrong_ids,
                             VectorRepo(conn), args.question)
        except IndexEmptyError:
            print("向量索引为空,请先运行: python -m interview_agent index")
            sys.exit(0)
        except LLMAPIError as e:
            # 4xx from the API: quiz-style Chinese message; no stats print
            # because ask has no topic context.
            print(f"LLM 接口错误(状态码 {e.status_code}),请检查 .env 配置")
            sys.exit(1)
        except LLMConnectionError:
            # Network failure: mirror the quiz branch message.
            print("LLM 连接失败,请检查网络与 .env 配置")
            sys.exit(1)
        print(answer)
        return

    if args.cmd == "eval":
        # Golden-set eval run: grade every case through the real agent loop
        # (storage-isolated by run_eval), print the table, persist a dated
        # markdown report. Exit code is always 0: an eval failure is a
        # finding, not a CLI error.
        golden_path = os.path.join(os.path.dirname(__file__), "data",
                                   "golden.json")
        if not os.path.exists(golden_path):
            print("未找到黄金集文件,请先生成 interview_agent/data/golden.json")
            sys.exit(0)
        with open(golden_path, encoding="utf-8") as f:
            golden = json.load(f)
        try:
            validate_golden(golden, qrepo)
            report = run_eval(LLMClient(cfg), qrepo, golden,
                              sample=args.sample)
        except ValueError as e:
            # unknown golden question_id, or --sample over the case count
            print(e)
            sys.exit(0)
        except LLMAPIError as e:
            # 4xx from the API: same Chinese message as index/ask branches.
            print(f"LLM 接口错误(状态码 {e.status_code}),请检查 .env 配置")
            sys.exit(0)
        except LLMConnectionError:
            # Network failure: mirror the index/ask branch message.
            print("LLM 连接失败,请检查网络与 .env 配置")
            sys.exit(0)
        print(report.format_table())
        out_dir = os.path.join("docs", "eval")
        os.makedirs(out_dir, exist_ok=True)
        out = os.path.join(out_dir, f"report-{date.today().isoformat()}.md")
        report.write_markdown(out, model=cfg.model)
        print(f"报告已写入: {out}")
        return

    # quiz: interactive loop with session persistence (topic is session id).
    driver = SessionDriver(LLMClient(cfg), qrepo, AttemptRepo(conn))
    store, _backend = make_session_store(cfg, conn)
    if args.resume:
        loaded = store.load(args.topic)
        if loaded is not None:
            driver.messages = loaded
            # Restore the asked set too, or the wrong-first policy would
            # re-ask questions the previous session already covered.
            driver.asked = rebuild_asked(loaded)
            print(f"已恢复上次会话({len(loaded)} 条消息)")
        else:
            print("没有找到可恢复的会话,从新会话开始")
    try:
        while True:
            driver.ask(args.topic, args.wrong_only)
            # pick_question returns {"message": ...} instead of a question
            # when nothing is available (parked from T2); exit gracefully.
            if "question_id" not in driver.current:
                # Differentiate: wrong-only exhausted vs unknown topic.
                if args.wrong_only:
                    print("当前没有待复习的错题,试试不带 --wrong-only")
                else:
                    print(f"没有找到 topic '{args.topic}' 的题目,请检查 topic 拼写"
                          "(jvm/thread_pool/mysql/network/os/redis/netty_algo/agent)")
                sys.exit(0)
            ans = input("你的回答(回车提交):\n> ")
            driver.grade(ans)
            store = save_with_fallback(store, conn, args.topic,
                                       driver.messages)
    except (KeyboardInterrupt, EOFError):
        store = save_with_fallback(store, conn, args.topic, driver.messages)
        print("\n本次统计:", AttemptRepo(conn).stats(args.topic))
        sys.exit(0)
    except LLMConnectionError:
        # Network/API failure mid-session: attempts already recorded via
        # record_result persist in SQLite; also save the session, then
        # report and exit non-zero.
        store = save_with_fallback(store, conn, args.topic, driver.messages)
        print("LLM 连接失败,请检查网络与 .env 配置(已答记录已保存)")
        print("本次统计:", AttemptRepo(conn).stats(args.topic))
        sys.exit(1)
    except LLMAPIError as e:
        # 4xx from the API (bad key etc.): no retry, readable Chinese message.
        store = save_with_fallback(store, conn, args.topic, driver.messages)
        print(f"LLM 接口错误(状态码 {e.status_code}),请检查 .env 配置(已答记录已保存)")
        print("本次统计:", AttemptRepo(conn).stats(args.topic))
        sys.exit(1)


if __name__ == "__main__":
    main()
