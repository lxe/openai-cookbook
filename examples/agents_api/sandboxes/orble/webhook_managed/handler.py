# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "orble-sdk>=0.1.3",
#     "fastapi>=0.115,<1",
#     "uvicorn>=0.30,<1",
#     "openai>=3.13.0",
# ]
# ///

"""A single-process OpenAI webhook controller hosted in an Orble box."""

from __future__ import annotations

import asyncio
import json
import os
import sqlite3
import sys
import time
import traceback
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import orble
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from openai import AsyncOpenAI, InvalidWebhookSignatureError, NotFoundError, OpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sandbox import box_name, find_box, install_executor, start_executor

DB_PATH = os.environ.get("QUEUE_PATH", "/home/agent/app/pending.sqlite3")
EVENTS = {
    "agent.session.action_required",
    "agent.session.in_progress",
    "agent.session.idle",
    "agent.session.failed",
}


def log(**fields: str) -> None:
    print(json.dumps(fields), flush=True)


def provision(session_id: str, remote_url: str, environment_id: str) -> str:
    """Resume the session's box, or create one, and make sure its executor runs."""
    box = find_box(session_id)
    if box is None:
        box = orble.create(name=box_name(session_id))
        action = "created"
    else:
        action = "resumed"
    # Waking a suspended box brings back its memory: an executor that was running reconnects by itself.
    box.keep_awake()
    install_executor(box, reconnect=True)
    start_executor(
        box, remote_url, environment_id, os.environ["OPENAI_EXECUTOR_API_KEY"]
    )
    return action


def set_awake(session_id: str, on: bool) -> None:
    box = find_box(session_id)
    if box is not None:
        # Off: the box suspends once nothing runs in it for a minute, with its processes kept.
        box.keep_awake(on)
        log(
            session_id=session_id,
            box=box.name,
            action="keep_awake" if on else "may_suspend",
        )


async def reconcile(session_id: str) -> None:
    async with AsyncOpenAI(timeout=30) as client:
        try:
            session = await client.beta.agents.sessions.retrieve(session_id)
        except NotFoundError:
            return
    if (
        session.environment.type != "self_hosted"
        or session.agent.id != os.environ["OPENAI_AGENT_ID"]
    ):
        return
    action = next(
        (a for a in session.required_actions if a.type == "environment_connection"),
        None,
    )
    if session.status == "failed":
        box = await asyncio.to_thread(find_box, session_id)
        if box is not None:
            await asyncio.to_thread(box.delete)
            log(session_id=session_id, box=box.name, action="deleted")
    elif action is not None:
        done = await asyncio.to_thread(
            provision,
            session_id,
            session.environment.remote_url,
            session.environment.id,
        )
        log(session_id=session_id, box=box_name(session_id), action=done)
    elif session.status == "in_progress":
        await asyncio.to_thread(set_awake, session_id, True)
    elif session.status == "idle":
        await asyncio.to_thread(set_awake, session_id, False)


async def drain_queue(db: sqlite3.Connection) -> None:
    while True:
        row = db.execute(
            "SELECT session_id, attempts FROM jobs WHERE retry_at <= ? LIMIT 1",
            (time.time(),),
        ).fetchone()
        if row is None:
            await asyncio.sleep(1)
            continue
        session_id, attempts = row
        try:
            await reconcile(session_id)
        except Exception as error:
            # Persist retries across controller process restarts; never log secrets.
            if attempts >= 4:
                db.execute("DELETE FROM jobs WHERE session_id = ?", (session_id,))
            else:
                db.execute(
                    "UPDATE jobs SET attempts = ?, retry_at = ? WHERE session_id = ?",
                    (attempts + 1, time.time() + 10, session_id),
                )
            log(
                session_id=session_id,
                error_type=type(error).__name__,
                error_at=" ".join(
                    f"{frame.name}:{frame.lineno}"
                    for frame in traceback.extract_tb(error.__traceback__)
                ),
            )
        else:
            db.execute("DELETE FROM jobs WHERE session_id = ?", (session_id,))
        db.commit()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db = sqlite3.connect(DB_PATH)
    db.execute(
        "CREATE TABLE IF NOT EXISTS jobs (session_id TEXT PRIMARY KEY, attempts INTEGER DEFAULT 0, retry_at REAL DEFAULT 0)"
    )
    app.state.db = db
    task = asyncio.create_task(drain_queue(db))
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        db.close()


app = FastAPI(lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


@app.post("/webhook")
async def webhook(request: Request) -> JSONResponse:
    secret = os.environ.get("OPENAI_WEBHOOK_SECRET")
    if not secret or secret == "pending-webhook-registration":
        return JSONResponse({"error": "Webhook not configured"}, status_code=503)
    payload = (await request.body()).decode()
    with OpenAI(api_key="unused", webhook_secret=secret) as verifier:
        try:
            verifier.webhooks.verify_signature(payload=payload, headers=request.headers)
        except (InvalidWebhookSignatureError, ValueError):
            return JSONResponse({"error": "Invalid signature"}, status_code=400)
    event = json.loads(payload)
    if event["type"] in EVENTS:
        # The job reads the session's current state, so a late or repeated event does no harm.
        request.app.state.db.execute(
            "INSERT INTO jobs(session_id) VALUES (?) ON CONFLICT(session_id) DO UPDATE SET retry_at = 0",
            (event["data"]["id"],),
        )
        request.app.state.db.commit()
        log(event_id=event["id"], session_id=event["data"]["id"], action="enqueued")
    return JSONResponse({"ok": True})


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
