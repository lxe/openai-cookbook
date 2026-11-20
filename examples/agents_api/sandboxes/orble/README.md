# Orble sandboxes

Run Agents API tasks with `codex exec-server` in [Orble](https://orble.tech) boxes, Linux VMs that suspend with
their memory and resume with their processes running:

- [Application-managed](application_managed/README.md): create a box, run a task, suspend and resume the box between
  turns, read its output, and delete the box and session.
- [Webhook-managed](webhook_managed/README.md): deploy a controller that creates a box per session, lets it suspend
  between turns, and resumes it when a session needs a connection.

Both modes use [sandbox.py](sandbox.py) for executor installation and launch. Boxes receive only the restricted
executor key, passed to the executor's own process; application credentials stay in the application or webhook
controller.
