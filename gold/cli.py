"""Command line: run any GOLD component, ask a question, review feedback, and each app's own commands.

    gold serve orchestrator|registry|scripted-model|<any app component>
    gold apps                                       the apps this GOLD serves, and their components
    gold ask "What was revenue by country last year?" [--app data-analyst] [--url http://localhost:8080]
    gold feedback list | dismiss ID                 review what users flagged (apps add more, e.g. promote)

Apps add commands (the data app: eval, bench, dataset, verify-queries, aiperf-*). Run `gold --help` for all.
"""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import httpx

PLATFORM_COMPONENTS = {
    "orchestrator": "gold.orchestrator.app",
    "registry": "gold.registry",
    "scripted-model": "gold.testing.scripted_model",
}


def ask(url: str, question: str, app: str | None, show_trace: bool) -> int:
    resp = httpx.post(f"{url.rstrip('/')}/api/ask", json={"question": question, "app": app}, timeout=600)
    if resp.status_code != 200:
        print(f"Error {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1
    body = resp.json()
    print(body["answer"])
    for action in body.get("actions", []):
        print(f"\nWaiting for approval (in the web app): {action['summary']}")
    if show_trace:
        print("\n--- how this answer was made ---")
        for call in body["calls"]:
            print(f"\n{call['agent']} ({call['elapsed_ms']} ms): {call['request']}")
            for step in call["steps"]:
                print(f"  - {step['tool']}: {json.dumps(step['input'])[:200]}")
        u = body["usage"]
        print(f"\n{u.get('model_requests', 0)} model calls, {u.get('total_tokens', 0)} tokens, {body['elapsed_ms']} ms")
    return 0


def load_env_file(path: str = ".env") -> None:
    """Read KEY=VALUE lines from .env without overriding variables already set."""
    file = Path(path)
    if not file.is_file():
        return
    for line in file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.split(" #", 1)[0].strip().strip('"').strip("'"))


def main() -> None:
    if len(sys.argv) > 1 and sys.argv[1] not in ("serve", "ask", "-h", "--help"):
        # Engineer commands run on your machine: read .env, and reach the
        # Compose database on localhost unless told otherwise.
        load_env_file()
        os.environ.setdefault("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@localhost:5432/gold")
    try:
        _main()
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:  # friendly message for the common setup mistakes
        import psycopg

        if isinstance(exc, psycopg.OperationalError):
            host = os.environ.get("GOLD_DATABASE_URL", "").rsplit("@", 1)[-1]
            sys.exit(f"Cannot reach the database at {host}. Set GOLD_DATABASE_URL. ({str(exc).splitlines()[0]})")
        raise


def _main() -> None:
    from gold import apps

    components = {**PLATFORM_COMPONENTS, **apps.components()}
    app_clis = [importlib.import_module(a.cli) for a in apps.all_apps().values() if a.cli]

    parser = argparse.ArgumentParser(prog="gold", description="GOLD: an enterprise agentic AI reference architecture")
    sub = parser.add_subparsers(dest="command", required=True)
    serve = sub.add_parser("serve", help="run one component")
    serve.add_argument("component", choices=sorted(components))
    sub.add_parser("apps", help="list the apps this GOLD serves")
    q = sub.add_parser("ask", help="ask the orchestrator a question")
    q.add_argument("question")
    q.add_argument("--app", help="which app answers (default: the orchestrator's default app)")
    q.add_argument("--url", default="http://localhost:8080")
    q.add_argument("--no-trace", action="store_true", help="print only the answer")
    fb = sub.add_parser("feedback", help="review user feedback (needs GOLD_CURATOR_DATABASE_URL)")
    fbs = fb.add_subparsers(dest="action", required=True)
    fl = fbs.add_parser("list", help="show feedback waiting for review")
    fl.add_argument("--status", default="new", choices=["new", "promoted", "dismissed"])
    fl.add_argument("--app", help="only this app's feedback")
    fd = fbs.add_parser("dismiss", help="close a feedback item without changes")
    fd.add_argument("id", type=int)
    fd.add_argument("--reviewed-by", required=True)
    for module in app_clis:
        module.register(sub, {"feedback": fbs})
    args = parser.parse_args()

    if args.command == "serve":
        importlib.import_module(components[args.component]).main()
    elif args.command == "apps":
        for app in apps.all_apps().values():
            print(f"{app.name}: {app.title}. {app.description}")
            print(f"  agents: {', '.join(app.agents) or '-'}")
            print(f"  components: {', '.join(app.components) or '-'}")
    elif args.command == "ask":
        sys.exit(ask(args.url, args.question, args.app, not args.no_trace))
    elif args.command == "feedback" and args.action in ("list", "dismiss"):
        from gold import feedback

        try:
            if args.action == "list":
                for item in feedback.list_items(args.status, args.app):
                    print(f"#{item['id']}  {item['app'] or '-'}  {item['rating']:4}  {item['user'] or '-'}  {item['question']}")
                    for label in ("sql_ran", "corrected_sql", "comment"):
                        if item[label]:
                            print(f"      {label}: {item[label]}")
            else:
                feedback.dismiss(args.id, args.reviewed_by)
                print(f"Dismissed #{args.id}")
        except feedback.FeedbackError as exc:
            sys.exit(str(exc))
    elif not any(module.run(args) for module in app_clis):
        parser.error(f"No app handles '{args.command}'.")


if __name__ == "__main__":
    main()
