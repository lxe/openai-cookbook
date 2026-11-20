# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "orble-sdk>=0.1.2",
# ]
# ///

"""Deploy a signature-protected controller in a dedicated Orble box."""

from __future__ import annotations

import json
import os
from pathlib import Path

import orble

ROOT = Path(__file__).parent
STATE = ROOT / ".controller.json"
APP = "/home/agent/app"
VENV = "/home/agent/controller"


def run(box: orble.Box, command: str, **kwargs: object) -> None:
    result = box.exec(command, **kwargs)
    if result.code != 0:
        raise RuntimeError(f"{command[:60]}: {result.stderr[-2000:]}")


def main() -> None:
    values = {
        key: os.environ[key]
        for key in [
            "OPENAI_API_KEY",
            "OPENAI_EXECUTOR_API_KEY",
            "OPENAI_AGENT_ID",
            "ORBLE_API_KEY",
        ]
    }
    values["OPENAI_WEBHOOK_SECRET"] = os.environ.get(
        "OPENAI_WEBHOOK_SECRET", "pending-webhook-registration"
    )
    if STATE.exists():
        box = orble.Box(json.loads(STATE.read_text())["box"])
    else:
        box = orble.create()
        STATE.write_text(json.dumps({"box": box.name}) + "\n")
    # The controller must answer webhooks at once, so its box never suspends.
    box.keep_awake()
    run(box, f"mkdir -p {APP}/webhook_managed")
    box.write(
        f"{APP}/webhook_managed/handler.py", ROOT.joinpath("handler.py").read_text()
    )
    box.write(f"{APP}/sandbox.py", ROOT.parent.joinpath("sandbox.py").read_text())
    run(
        box,
        f"test -x {VENV}/bin/uv || (python3 -m venv {VENV} && {VENV}/bin/pip install -q uv)"
        f" && {VENV}/bin/uv pip install -q --python {VENV}/bin/python -r {APP}/webhook_managed/handler.py",
        timeout=300,
    )
    box.exec(f"pkill -f '^{VENV}/bin/python -m uvicorn handler:app' || true")
    run(
        box,
        f"setsid nohup {VENV}/bin/python -m uvicorn handler:app --host 0.0.0.0 --port 8000"
        f" >> {APP}/controller.log 2>&1 < /dev/null &",
        cwd=f"{APP}/webhook_managed",
        env=values,
    )
    url = box.port(8000, public=True)
    print(f"Webhook: {url.rstrip('/')}/webhook")
    print(f"Controller: {box.name}")


if __name__ == "__main__":
    main()
