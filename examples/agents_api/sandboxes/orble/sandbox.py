"""Executor setup and launch shared by the two Orble examples."""

import hashlib
import shlex

import orble

WORKSPACE = "/workspace"
LOG = "/tmp/codex-executor.log"
LOCK = "/tmp/codex-executor.lock"


def box_name(session_id: str) -> str:
    """The box for an API session: one per session, found again by name."""
    return "agents-" + hashlib.sha256(session_id.encode()).hexdigest()[:16]


def find_box(session_id: str) -> orble.Box | None:
    box = orble.Box(box_name(session_id))
    try:
        box.refresh()
    except orble.Error as error:
        if error.status == 404:
            return None
        raise
    return box


def install_executor(box: orble.Box, *, reconnect: bool = False) -> None:
    # npm's global prefix belongs to agent. The box image has a release build of Codex; the executor needs alpha.
    install = "npm install -g @openai/codex@alpha"
    if reconnect:
        install = f"(npm ls -g @openai/codex | grep -q alpha || {install})"
    result = box.exec(
        f"sudo mkdir -p {WORKSPACE} && sudo chown agent:agent {WORKSPACE} && {install}",
        timeout=300,
    )
    if result.code != 0:
        raise RuntimeError(f"Codex install failed: {result.stderr[-2000:]}")


def start_executor(
    box: orble.Box, remote_url: str, environment_id: str, executor_key: str
) -> None:
    """Start `codex exec-server` in the background, unless it is already running."""
    args = [
        "flock",
        "-n",
        LOCK,
        "codex",
        "exec-server",
        "--remote",
        remote_url,
        "--environment-id",
        environment_id,
    ]
    # The key reaches only this command's environment; it is not written to the box's disk.
    box.exec(
        f"setsid nohup {shlex.join(args)} >> {LOG} 2>&1 < /dev/null &",
        cwd=WORKSPACE,
        env={"CODEX_API_KEY": executor_key},
    )


def executor_pid(box: orble.Box) -> str:
    return box.exec("pgrep -f '^codex exec-server' | head -1").stdout.strip()
