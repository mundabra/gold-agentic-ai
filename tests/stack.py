"""Start the whole GOLD stack as local processes (used by the end-to-end test and for development).

    python tests/stack.py            # scripted test model, no API key needed
    GOLD_LLM_BASE_URL=... GOLD_LLM_API_KEY=... python tests/stack.py --real-model

Needs Postgres with deploy/postgres/* loaded; set GOLD_DATABASE_URL.
"""

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))   # so `python tests/stack.py` can import gold, as pytest can
PORTS = {
    "fake-llm": 4010,
    "registry": 18000,
    "mcp-data": 18001,
    "mcp-glossary": 18002,
    "sql-agent": 18003,
    "definitions-agent": 18004,
    "mcp-crm": 18005,
    "account-agent": 18006,
    "mcp-knowledge": 18007,
    "orchestrator": 18080,
}


def base_env(real_model: bool) -> dict:
    env = dict(os.environ)
    env.setdefault("GOLD_DATABASE_URL", "postgresql://gold_reader:gold_reader@localhost:55432/gold")
    if not real_model:
        env["GOLD_LLM_BASE_URL"] = f"http://127.0.0.1:{PORTS['fake-llm']}/v1"
        env["GOLD_LLM_API_KEY"] = "scripted"
    env["GOLD_HOST"] = "127.0.0.1"
    env["GOLD_REGISTRY_URL"] = f"http://127.0.0.1:{PORTS['registry']}"
    env["GOLD_DATA_MCP_URL"] = f"http://127.0.0.1:{PORTS['mcp-data']}/mcp"
    env["GOLD_GLOSSARY_MCP_URL"] = f"http://127.0.0.1:{PORTS['mcp-glossary']}/mcp"
    env["GOLD_CRM_MCP_URL"] = f"http://127.0.0.1:{PORTS['mcp-crm']}/mcp"
    env["GOLD_KNOWLEDGE_MCP_URL"] = f"http://127.0.0.1:{PORTS['mcp-knowledge']}/mcp"
    env.setdefault("GOLD_KNOWLEDGE_URL", env["GOLD_DATABASE_URL"].replace("gold_reader:gold_reader", "gold_knowledge:gold_knowledge"))
    env.setdefault("GOLD_CRM_DATABASE_URL", env["GOLD_DATABASE_URL"].replace("gold_reader:gold_reader", "gold_crm_writer:gold_crm_writer"))
    env["PYTHONUNBUFFERED"] = "1"
    return env


def wait_for(url: str, timeout: float = 30) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url, timeout=1).status_code == 200:
                return
        except httpx.HTTPError:
            pass
        time.sleep(0.3)
    raise TimeoutError(f"{url} did not come up")


def start(real_model: bool = False, log_dir: Path | None = None) -> list[subprocess.Popen]:
    env = base_env(real_model)
    log_dir = log_dir or ROOT / ".stack-logs"
    log_dir.mkdir(exist_ok=True)
    procs = []

    def launch(name: str, args: list[str], health: str) -> None:
        e = dict(env, GOLD_PORT=str(PORTS[name]), GOLD_PUBLIC_URL=f"http://127.0.0.1:{PORTS[name]}")
        log = open(log_dir / f"{name}.log", "w")
        procs.append(subprocess.Popen(args, cwd=ROOT, env=e, stdout=log, stderr=subprocess.STDOUT))
        wait_for(f"http://127.0.0.1:{PORTS[name]}{health}")

    py = sys.executable
    if not real_model:
        launch("fake-llm", [py, "-m", "gold.cli", "serve", "scripted-model"], "/healthz")
    launch("registry", [py, "-m", "gold.cli", "serve", "registry"], "/healthz")
    launch("mcp-data", [py, "-m", "gold.cli", "serve", "mcp-data"], "/healthz")
    launch("mcp-glossary", [py, "-m", "gold.cli", "serve", "mcp-glossary"], "/healthz")
    launch("sql-agent", [py, "-m", "gold.cli", "serve", "sql-agent"], "/healthz")
    launch("definitions-agent", [py, "-m", "gold.cli", "serve", "definitions-agent"], "/healthz")
    launch("mcp-knowledge", [py, "-m", "gold.cli", "serve", "mcp-knowledge"], "/healthz")
    launch("mcp-crm", [py, "-m", "gold.cli", "serve", "mcp-crm"], "/healthz")
    launch("account-agent", [py, "-m", "gold.cli", "serve", "account-agent"], "/healthz")
    launch("orchestrator", [py, "-m", "gold.cli", "serve", "orchestrator"], "/healthz")

    # Wait until every specialist has registered.
    deadline = time.time() + 30
    while time.time() < deadline:
        names = {a["name"] for a in httpx.get(f"http://127.0.0.1:{PORTS['registry']}/agents").json()}
        if {"SQL agent", "Definitions agent", "Account agent"} <= names and knowledge_loaded(env):
            return procs
        time.sleep(0.5)
    stop(procs)
    raise TimeoutError("agents did not register, or the knowledge documents did not load")


def knowledge_loaded(env: dict) -> bool:
    """The knowledge server loads the apps' documents in the background; wait for them."""
    from gold.knowledge import open_store

    try:
        return open_store(env["GOLD_KNOWLEDGE_URL"]).collections().get("sales-playbook", 0) > 0
    except Exception:
        return False


def stop(procs: list[subprocess.Popen]) -> None:
    for p in procs:
        p.send_signal(signal.SIGTERM)
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
            p.wait()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--real-model", action="store_true", help="use GOLD_LLM_BASE_URL instead of the scripted test model")
    args = parser.parse_args()
    running = start(real_model=args.real_model)
    signal.signal(signal.SIGTERM, signal.default_int_handler)  # stop the services on kill, too
    print(f"GOLD is running: http://127.0.0.1:{PORTS['orchestrator']}  (Ctrl+C to stop)")
    try:
        signal.pause()
    except KeyboardInterrupt:
        pass
    finally:
        stop(running)
