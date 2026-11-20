# Application-managed Orble box

The application creates an Agents API session and an Orble box, starts `codex exec-server`, and asks the agent to
turn `brief.txt` into `plan.md`. Then it suspends the box, resumes it, and asks for a sixth step: the box comes
back with the same executor process, which reconnects to the session. It prints the plan, deletes the box, and
deletes the session.

## Run

Set `ORBLE_API_KEY` (from [Settings](https://orble.tech/settings?tab=api)), `OPENAI_API_KEY`, and a separate
restricted `OPENAI_EXECUTOR_API_KEY`. The OpenAI keys must have the same owner, organization, and project. Only
the executor key enters the box. The Orble account needs an SSH key (`orble keys add`), which every box gets.

From the Cookbook repository root:

```bash
uv run examples/agents_api/sandboxes/orble/application_managed/main.py
```

Dependencies are declared inline. The script allows ten minutes for setup and both turns and attempts both cleanup
operations on failure. The box is kept awake while the script runs; without that, a box suspends after a minute
with nothing running. If creation fails after the box was made, find it with `orble ls` by the `agents-` name the
script printed and delete it with `orble rm`.

For follow-up turns, keep both resources until the application is finished. Between turns, `box.suspend()` or
`box.keep_awake(False)` stops billing for CPU while keeping files, memory, and the executor; `box.resume()` brings
it back. Do not attach a provisioning webhook handler to these sessions.

## References

- [Orble documentation](https://orble.tech/docs)
- [Orble Python SDK](https://orble.tech/docs?tab=python)
- [Webhook-managed example](../webhook_managed/README.md)
