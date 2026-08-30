from __future__ import annotations

import argparse

from smart_ask_data.config import load_settings
from smart_ask_data.factory import create_service
from smart_ask_data.logging import configure_logging
from smart_ask_data.models import AskRequest


def create_app():
    """Backward-compatible workflow factory used by the original demo tests."""
    return create_service().workflow


def ask(app, question: str, debug: bool = False) -> str:
    result = app.invoke({"question": question, "retry_count": 0, "trace": []})
    if debug:
        print("SQL:", result.get("sql", "未生成"))
        print("Trace:", " -> ".join(result.get("trace", [])))
    return result["answer"]


def main() -> None:
    parser = argparse.ArgumentParser(description="智能问数系统")
    parser.add_argument("question", nargs="?", help="自然语言问题")
    parser.add_argument("--interactive", action="store_true", help="进入交互模式")
    parser.add_argument("--debug", action="store_true", help="显示 SQL、评分和执行轨迹")
    args = parser.parse_args()
    settings = load_settings()
    configure_logging(settings.app.log_level)
    service = create_service(settings)

    def run(question: str) -> None:
        response = service.ask(AskRequest(question=question, debug=args.debug))
        print(response.answer)
        if args.debug:
            print("Request ID:", response.request_id)
            print("SQL:", response.sql or "未生成")
            print("Scores:", response.scores)
            print("Trace:", " -> ".join(response.trace))

    if args.interactive:
        while True:
            question = input("问题（输入 exit 退出）> ").strip()
            if question.lower() in {"exit", "quit"}:
                break
            run(question)
    elif args.question:
        run(args.question)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
