# Orble webhook-managed box

A controller in a dedicated Orble box receives OpenAI webhooks and queues work in SQLite. It creates or resumes a
separate worker box for each API session. Agent commands run only in the worker box.

## Deploy

Create an agent using the [shared setup](../../webhook_managed.md#set-up-once). Run the deployment command below
from the Cookbook repository root.

Set `OPENAI_AGENT_ID` to the agent ID from the shared setup. Provide it alongside `ORBLE_API_KEY`,
`OPENAI_API_KEY`, and `OPENAI_EXECUTOR_API_KEY` through your secret manager. The two OpenAI keys must match the
session owner's organization, project, and user or service account. The Orble account needs an SSH key
(`orble keys add`), and public ports need an account that has added credit.

```bash
uv run examples/agents_api/sandboxes/orble/webhook_managed/deploy.py
```

The deployment saves the controller box's name in `.controller.json` beside `deploy.py`. Keep that
file to redeploy the same controller and retain its queue.

Register the printed URL in **OpenAI project settings → Webhooks**, subscribing to
`agent.session.action_required`, `agent.session.in_progress`, `agent.session.idle`, and `agent.session.failed`.
Set the generated `OPENAI_WEBHOOK_SECRET` locally and redeploy. Then use the
[run and reconnect guide](../../webhook_managed.md#run-and-reconnect) with this provider's client:

```bash
uv run examples/agents_api/sandboxes/orble/webhook_managed/client.py --agent-id "$OPENAI_AGENT_ID"
```

The public webhook endpoint verifies each delivery's signature. Worker boxes receive only the restricted executor
key, in the executor's environment. The application key, Orble key, and signing secret stay in the controller. Run
one controller process. Its queue survives process restarts and suspends, not deletion of the controller box.
Failed provisioning gets up to five attempts.

## Lifecycle

| Current state | Handler action |
| --- | --- |
| Connection required, no worker | Create a worker, keep it awake, and launch the executor. |
| Connection required, suspended worker | Resume the same worker; its executor comes back with it and reconnects. |
| Turn in progress | Keep the worker awake. |
| Session idle | Let the worker suspend once nothing runs in it for a minute. |
| Session failed | Delete its worker. |
| Other agent or resolved action | Do not provision or stop compute. |

The handler reads each session's current state before acting, so late or repeated events do no harm. A worker
suspends only after the box itself has been idle for a minute, so a new turn that starts in the meantime finds it
running.

## Stop or clean up

The controller logs each session's box name. A suspended worker keeps its files, memory, and running processes,
and costs only storage; the next input makes the handler resume it. Deleting it instead causes the next input to
create a fresh box, without previous files. The handler finds workers by name, derived from the session ID.

For final cleanup, delete the API session and its Orble box separately (`orble rm`), including suspended workers.
Remove the OpenAI webhook before deleting the controller box. The controller box stays awake; it has no time limit.

Controller logs are in `/home/agent/app/controller.log` in the controller box; executor logs are in
`/tmp/codex-executor.log` inside each worker.
