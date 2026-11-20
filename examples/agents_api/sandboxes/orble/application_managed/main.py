# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "openai>=3.13.0",
#     "orble-sdk>=0.1.3",
# ]
# ///

"""Run two Agents API turns in an Orble box, suspended between them, and clean up both resources."""

import asyncio
import os
import sys
from pathlib import Path

import orble
from openai import AsyncOpenAI

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from sandbox import WORKSPACE, box_name, executor_pid, install_executor, start_executor

BRIEF = "Migrate a synchronous Python service to async without changing its API.\n"
FAILED = {
    "error",
    "agent.session.environment.failed",
    "agent.session.failed",
    "agent.session.turn.failed",
    "agent.session.turn.cancelled",
}


async def run_turn(client: AsyncOpenAI, session_id: str, text: str) -> None:
    async with client.beta.agents.sessions.stream(session_id, input=text) as events:
        async for event in events:
            if event.type in FAILED:
                raise RuntimeError(f"Agent failed: {event.type}")
            if event.type == "agent.session.turn.output_text.delta":
                print(event.delta, end="", flush=True)
    print()


async def main() -> None:
    executor_key = os.environ["OPENAI_EXECUTOR_API_KEY"]
    async with AsyncOpenAI(timeout=360) as client:
        session = await client.beta.agents.sessions.create(
            agent={"model": "gpt-5.6-sol"},
            environment={"type": "self_hosted", "workspace_directory": WORKSPACE},
        )
        box = None
        print(f"Session: {session.id}", flush=True)
        try:
            assert session.environment.type == "self_hosted"
            async with asyncio.timeout(600):
                box = await asyncio.to_thread(orble.create, name=box_name(session.id))
                print(f"Box: {box.name}", flush=True)
                # Idle boxes suspend after a minute; keep this one up while the agent works.
                await asyncio.to_thread(box.keep_awake)
                await asyncio.to_thread(install_executor, box)
                await asyncio.to_thread(box.write, f"{WORKSPACE}/brief.txt", BRIEF)
                await asyncio.to_thread(
                    start_executor,
                    box,
                    session.environment.remote_url,
                    session.environment.id,
                    executor_key,
                )
                await run_turn(
                    client,
                    session.id,
                    "Read brief.txt and write a five-step migration plan to plan.md.",
                )
                plan = await asyncio.to_thread(box.read, f"{WORKSPACE}/plan.md")
                if not plan.strip():
                    raise RuntimeError("The agent did not write a migration plan")
                print(f"\nplan.md:\n{plan}")

                # Between turns the box can be suspended. Its memory is saved with it, so the same
                # executor process comes back on resume and reconnects to the session.
                pid = await asyncio.to_thread(executor_pid, box)
                await asyncio.to_thread(box.suspend)
                print(f"Suspended {box.name} with executor {pid}", flush=True)
                await asyncio.to_thread(box.resume)
                print(
                    f"Resumed {box.name} with executor {await asyncio.to_thread(executor_pid, box)}"
                )

                await run_turn(
                    client, session.id, "Add a sixth step to plan.md: how to roll back."
                )
                plan = await asyncio.to_thread(box.read, f"{WORKSPACE}/plan.md")
                print(f"\nplan.md:\n{plan}")
        finally:
            try:
                if box is not None:
                    async with asyncio.timeout(30):
                        await asyncio.to_thread(box.delete)
            finally:
                async with asyncio.timeout(30):
                    await client.beta.agents.sessions.delete(session.id)


if __name__ == "__main__":
    asyncio.run(main())
