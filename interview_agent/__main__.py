# interview_agent/__main__.py
# CLI entry: argparse (quiz subcommand) + interactive loop + graceful exit.
import argparse
import os
import sys

from .config import load_config
from .store.db import connect, init_schema
from .store.questions import QuestionRepo
from .store.attempts import AttemptRepo
from .llm.client import LLMClient, LLMConnectionError
from .session import SessionDriver


def main():
    p = argparse.ArgumentParser(prog="interview_agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    q = sub.add_parser("quiz")
    q.add_argument("--topic", required=True)
    q.add_argument("--wrong-only", action="store_true")
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
    driver = SessionDriver(LLMClient(cfg), qrepo, AttemptRepo(conn))
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
    except (KeyboardInterrupt, EOFError):
        print("\n本次统计:", AttemptRepo(conn).stats(args.topic))
        sys.exit(0)
    except LLMConnectionError:
        # Network/API failure mid-session: attempts already recorded via
        # record_result persist in SQLite, so just report and exit non-zero.
        print("LLM 连接失败,请检查网络与 .env 配置(已答记录已保存)")
        print("本次统计:", AttemptRepo(conn).stats(args.topic))
        sys.exit(1)


if __name__ == "__main__":
    main()
