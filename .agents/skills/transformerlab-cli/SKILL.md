---
name: transformerlab-cli
description: Transformer Lab CLI for managing ML training tasks, jobs, and compute providers. Use when the user needs to check job status, stream logs, download artifacts, queue training tasks, manage compute providers, or interact with Transformer Lab programmatically. Triggers include "check job status", "download results", "queue a task", "list providers", "stream logs", "what's running", "monitor training", "add a task", "check provider health".
allowed-tools: Bash(lab *), Bash(curl *beta.lab.cloud*), Bash(curl *localhost:8338*)
---

# Transformer Lab CLI

Use the `lab` CLI to interact with Transformer Lab programmatically — managing tasks, jobs, compute providers, and server configuration from the terminal.

## Installation

```bash
uv tool install transformerlab-cli
# or
pip install transformerlab-cli
```

Verify: `lab version`

## First-Time Setup & Authentication

**If the CLI returns `Missing required configuration keys: team_id, user_email` (or any other auth/config error), do NOT ask the user for an API key.** Instead, tell them to run:

```bash
lab login
```

This launches the interactive login flow in their terminal. Wait for them to complete it, then retry the original command. Never prompt the user to paste an API key into the conversation.

**The CLI only supports API key authentication.** There is no `--email` or `--password` flag. To connect:

```bash
# Step 1: Set the server (if not using default localhost)
lab config set server https://your-server-url

# Step 2: Login with an API key
lab login --api-key YOUR_API_KEY --server https://your-server-url

# Step 3: Set the current experiment
lab config set current_experiment your_experiment_name

# Step 4: Verify connectivity
lab status
```

`login` validates the key and automatically configures `server`, `team_id`, `user_email`, and `team_name`.

**Getting an API key:** API keys are created in the Transformer Lab web UI under team settings, or via the REST API using a JWT token. If the user gives you email/password credentials, get a JWT token first, then use it to create an API key:

```bash
# Get JWT token from email/password
TOKEN=$(curl -s -X POST https://SERVER/auth/jwt/login \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=EMAIL&password=PASSWORD" | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])")

# Use the JWT to find team info
curl -s -H "Authorization: Bearer $TOKEN" https://SERVER/users/me/teams
```

Then ask the user to provide or create an API key from the UI.

### Verifying You're Connected to the Right Server

After login, always verify:

```bash
lab config        # Shows server URL, team, user, experiment
lab status        # Shows server version and connectivity
lab whoami        # Confirms authenticated user and team
```

If `lab status` returns errors but `curl -s https://SERVER/` returns 200, the issue is likely auth — re-run `lab login`.

## Critical: `--format` Flag Placement

The `--format` flag is a **root-level option** and MUST come immediately after `lab`, before any subcommand:

```bash
# CORRECT
lab --format json job list
lab --format json task info 42

# WRONG — will be ignored or cause an error
lab job list --format json
```

## Core Workflow

The standard pattern for working with Transformer Lab:

```bash
# 1. Check server is up
lab status

# 2. List available tasks
lab task list

# 3. Queue a task on a compute provider
#    NOTE: --no-interactive silently picks the DEFAULT provider (Local).
#    To pick a specific provider, run interactively (see "Selecting a provider" below).
lab task queue TASK_ID --no-interactive

# 4. Monitor the job
lab job list --running
lab job task-logs JOB_ID --follow

# 5. Download results
lab job artifacts JOB_ID
lab job download JOB_ID --file "*.csv" -o ./results
```

## Agent-Specific Rules

1. **NEVER use the REST API unless the user explicitly asks for it.** The CLI is the supported interface. If a CLI command appears missing or broken, run `lab <command> --help` first and check this skill — do not reach for `curl`. Using the REST API as a workaround is a hard rule violation.
2. **Always run `lab <command> --help` before assuming a flag exists.** Don't guess `--provider`, `--gpu`, etc. The CLI's flag surface is small and changes; verify before invoking.
3. **Use `--format json`** when you need to parse output, but be prepared to fall back to pretty output parsing if it doesn't work
4. **`--no-interactive` on `task queue` silently uses the DEFAULT provider (Local).** There is no `--provider` flag. To target a specific provider, you must drive the interactive prompts (see "Selecting a provider" below).
5. **`task add` has no `--yes` flag** — pipe `echo "y"` to confirm: `echo "y" | lab task add ./my-task`
6. **Use `--yes` / `-y`** on destructive commands (`provider delete`) to skip confirmation
7. **Never use `job monitor`** — it launches a TUI that blocks; use `job list` + `job task-logs` instead
8. **Never use `task interactive`** unless the user specifically requests an interactive session
9. **`job task-logs --follow`** streams continuously and blocks until the job finishes — use when the user wants real-time monitoring
10. **Never use the deprecated `lab job logs`** — see the "Job logs: three real commands" section below.

### Selecting a provider when queuing a task

`lab task queue` has no `--provider` flag. With `--no-interactive` it picks the default (usually Local). To pick a specific provider, drive the interactive prompts via stdin. The flow is:

1. "Use these resource requirements? [Y/n]" → answer `y`
2. "Available Providers: 1. Local  2. skypilot1 ... Select a provider [1]:" → answer the number

```bash
# Pick provider #2 (skypilot1) with default resources
printf "y\n2\n" | lab task queue TASK_ID
```

Run `lab provider list` first to confirm the numbering before piping.

### Job logs: three real commands

`lab job logs` is **deprecated** — do not use it. There are three distinct log commands, each surfacing a different layer:

| Command | What it shows | When to use |
|---|---|---|
| `lab job task-logs JOB_ID` | Task (Lab SDK) output — what `lab.log()` recorded | Default for "what did my task do?" — covers `lab.log`, progress, completion |
| `lab job machine-logs JOB_ID` | Machine/provider stdout+stderr from the remote node | When the task crashed before SDK init, or you need raw process output |
| `lab job request-logs JOB_ID` | Provider request/launch logs (e.g. SkyPilot launch/provisioning) | When the cluster never started, or to debug provisioning failures |

All three accept `--follow` to stream continuously. Start with `task-logs`; escalate to `machine-logs` for crashes outside the SDK, and `request-logs` for cluster/provisioning issues.

## Debugging Failed Jobs

**Job COMPLETE does not mean the task succeeded.** Always check `completion_status` and `completion_details`:

```bash
# CLI: check job info for completion details
lab job info JOB_ID
# Look for: Completion Status (success/failed/N/A) and Completion Details

# CLI: get logs (see "Job logs: three real commands" above)
lab job task-logs JOB_ID      # task/SDK output
lab job machine-logs JOB_ID   # raw process stdout+stderr
lab job request-logs JOB_ID   # provider launch/provisioning logs
```

**Do NOT fall back to the REST API** if a log command returns empty — try the other two log commands first. The three layers surface different things; sparse output from one doesn't mean failure.

**Common failure patterns:**

| Symptom | Cause | Fix |
|---|---|---|
| Status COMPLETE but completion_status is N/A, progress 0% | Task never actually ran (wrong GPU type, cluster not found) | Check cluster status, verify accelerator type exists on provider |
| Status FAILED, "No such file or directory" in logs | Wrong `run` command path | Check where files are placed (see File Mounts section) |
| Status FAILED with a Python traceback | Task code error | Read the full provider logs to see the traceback |
| Status FAILED, no logs available | Cluster failed to provision | Check if the requested accelerator type is available |

### Checking Cluster Status (SkyPilot providers)

Use `lab job info JOB_ID` — it shows `cluster_name` and provisioning state. For more detail use `lab job request-logs JOB_ID` (provider launch logs). If a cluster never provisioned, the request-logs will show why (wrong accelerator type, quota, etc.).

## Do NOT use the REST API

The CLI is the supported, sanctioned interface. **Never call the REST API directly with `curl` unless the user explicitly asks you to.** If the CLI seems to be missing a capability:

1. Run `lab <command> --help` and `lab <subcommand> --help` to verify
2. Re-read this skill for the right pattern (e.g. interactive prompts via stdin)
3. Tell the user the CLI doesn't support it — don't silently switch to `curl`

This applies to launching jobs, fetching logs, checking cluster status, and everything else.

## Command Overview

| Command | Description | Requires Experiment |
|---|---|---|
| `lab status` | Check server connectivity | No |
| `lab config` | View/set CLI configuration | No |
| `lab login` | Authenticate with API key (sets server, team, user) | No |
| `lab logout` | Remove stored API key | No |
| `lab whoami` | Show current user and team | No |
| `lab version` | Show CLI version | No |
| `lab task list` | List tasks in current experiment | Yes |
| `lab task info <id>` | Get task details | Yes |
| `lab task add [dir]` | Add task from directory or `--from-git` URL | Yes |
| `lab task delete <id>` | Delete a task | Yes |
| `lab task queue <id>` | Queue task on compute provider | Yes |
| `lab task gallery` | Browse/import from task gallery | Yes |
| `lab job list` | List jobs (`--running` for active only) | Yes |
| `lab job info <id>` | Get detailed job information | Yes |
| `lab job task-logs <id>` | Fetch task/SDK output (`--follow` to stream) | Yes |
| `lab job machine-logs <id>` | Fetch raw machine/provider stdout+stderr (`--follow`) | Yes |
| `lab job request-logs <id>` | Fetch provider launch/provisioning logs | Yes |
| `lab job artifacts <id>` | List job artifacts | Yes |
| `lab job download <id>` | Download artifacts (`--file` for glob) | Yes |
| `lab job stop <id>` | Stop a running job | Yes |
| `lab provider list` | List compute providers | No |
| `lab provider info <id>` | Show provider details | No |
| `lab provider add` | Add a new provider | No |
| `lab provider update <id>` | Update provider config | No |
| `lab provider delete <id>` | Delete a provider (`--yes` to skip prompt) | No |
| `lab provider check <id>` | Check provider health | No |
| `lab provider enable <id>` | Enable a provider | No |
| `lab provider disable <id>` | Disable a provider | No |
| `lab server install` | Interactive server setup wizard | No |
| `lab server version` | Show installed server version | No |
| `lab server update` | Update server to latest | No |

## JSON Output Shapes

**`lab --format json job list`** returns an array:
```json
[{"id": "uuid", "status": "COMPLETE", "progress": 100, "job_data": {...}, "created_at": "..."}]
```

**`lab --format json task list`** returns an array:
```json
[{"id": "uuid", "name": "my-task", "type": "REMOTE", ...}]
```

**Errors** return:
```json
{"error": "error message here"}
```

With non-zero exit code.

## Error Handling

- Commands exit with non-zero status on failure
- With `--format json`, errors return `{"error": "<message>"}`
- "config not set" errors → run `lab login` first
- "current_experiment not set" → run `lab config set current_experiment <id>`
- Connection refused → check server URL with `lab config`, verify server is running
- "No compute providers available" → add a provider in team settings first, or check `provider list`

## When to Use CLI vs REST API vs Browser

| Use CLI for | Use REST API for | Use Browser for |
|---|---|---|
| Login, config, status checks | Launching jobs when CLI fails | Creating experiments |
| Listing tasks and jobs | Getting provider logs | Configuring tasks via forms |
| Streaming job logs (`--follow`) | Checking cluster status | Visual UI verification |
| Adding tasks from local dirs | Any operation where CLI returns errors | Creating API keys |
| Downloading artifacts | Debugging failed jobs | Managing team settings |

**When to fall back to REST API:** If any CLI command returns "Not Found", "Method Not Allowed", or "No compute providers available", the server API may have changed. Use the OpenAPI spec (`/openapi.json`) to find correct endpoints and call them directly with `curl`.

## Deep-Dive References

- `references/commands.md` — Full command reference with all options
- `references/workflows.md` — End-to-end workflow patterns
- `references/troubleshooting.md` — Error patterns and recovery

## Ready-to-Use Templates

- `templates/setup-and-login.sh` — First-time setup
- `templates/queue-and-monitor.sh` — Queue a task and monitor until completion
- `templates/provider-health-check.sh` — Check health of all providers
