# clockify-mcp

MCP server for [Clockify](https://clockify.me) — file time entries and query reports from Claude Code, Cowork, or any MCP client. Includes a `/log-session` command that turns the conversation you just had into a confirmed time entry.

- **`add_time_entry`** — file an entry with start, end, project, description.
- **`list_time_entries`** — your entries in a date range (single project filter, auto-paginated, totals included).
- **`report_summary`** — totals from the Reports API, grouped by PROJECT / TASK / USER / DAY / WEEK / MONTH / TAG / CLIENT. The right tool for *"how many hours did I log on project X between A and B?"*.
- **`report_detailed`** — raw entries across multiple projects/users, hydrated with names.
- **`list_projects`**, **`list_tasks`**, **`list_tags`**, **`list_workspaces`**, **`get_running_timer`**, **`stop_running_timer`**, **`update_time_entry`**, **`delete_time_entry`**, **`whoami`**.

Natural-language time inputs are accepted everywhere: `"today 09:00"`, `"yesterday 14:30"`, `"2h ago"`, `"now"`, plus full ISO-8601. The server converts to the user's IANA timezone (read from `GET /user`) before posting to Clockify.

## Connection model

| Mode | Audience | Auth | Use when |
|---|---|---|---|
| **stdio** (published default) | Claude Code, Cowork, Codex, local CLIs | Your API key in your operating system credential store | Normal use. Each person runs the bundled adapter on their own computer. |
| **HTTP + OAuth** (`--http`) | Legacy remote clients | OAuth 2.1 + PKCE | Temporary compatibility while an old remote installation is retired. |

Installing the plugin wires in the local stdio process automatically. Starting a
Claude or Codex session starts only that small local process. MCP initialization
and tool discovery do not read the Clockify key and do not contact Clockify.
The first Clockify network request happens only when a Clockify tool is invoked.

Every colleague installs the same plugin on their own computer and stores their
own Clockify key there. The plugin distributes code only. It does not distribute
any user's key, connection, or Clockify data.

## Install (stdio)

```bash
uv tool install --from . clockify-mcp     # or:  pip install -e .
```

## Configure

Get an API key from <https://app.clockify.me/user/preferences#advanced>, then
store it through the hidden local prompt:

```bash
uv run clockify-mcp --store-key
```

The command validates the key against Clockify before saving it in macOS
Keychain, Windows Credential Manager, or Linux Secret Service. It never prints
the key and does not put it in shell history.

The optional config file contains only nonsecret settings:

```toml
# Only if you use a Clockify regional shard:
# api_base = "https://euc1.api.clockify.me/api/v1"
# reports_api_base = "https://euc1.reports.api.clockify.me/v1"
# default_workspace_id = "..."
# timezone = "Europe/Zurich"
```

`CLOCKIFY_API_KEY` and the old plaintext `api_key` config entry remain accepted
only so existing installations can migrate without interruption.

Verify:

```bash
clockify-mcp --check
# OK. Authenticated as <Your Name> <your@email>
#   user_id:              …
#   default_workspace_id: …
#   active_workspace_id:  …
#   timezone:             …
```

## Wire into Claude Code

Add the server to your Claude Code config:

```bash
claude mcp add clockify -- clockify-mcp
```

Or edit `~/.claude.json` directly:

```json
{
  "mcpServers": {
    "clockify": {
      "command": "clockify-mcp"
    }
  }
}
```

Restart Claude Code. Verify the tools are loaded:

```
> /mcp
```

You should see `clockify` listed with ~13 tools.

## Use it

```
> Log the last 90 minutes to project "<your project>" as "<what you did>".
> How many hours did I log on project "<your project>" between <date> and <date>?
> Show me everything I logged this week, broken down by project.
> Stop my running timer.
```

The `/log-session` command is the dedicated end-of-session flow: it estimates duration from the conversation start, summarises what you did, asks for the project, then confirms before posting.

## Set your organisation's billing rules

The plugin's skills follow three universal rules: 15-min quantum, single entry ≤ 2h, never double-book the same project. Any **organisation-specific** rule (e.g. whether parallel work on different clients may overlap in time, which internal meetings to skip when reconciling your calendar) is *not* baked into the plugin — the skills look for it in your local memory.

If you have a billing convention, add it once to `~/.claude/CLAUDE.md`:

```markdown
## Clockify

<Your org's overlap policy: e.g. "parallel sessions for different clients
may overlap; same-client overlap is forbidden">

<Which internal meeting patterns to skip when scanning the calendar>
```

Claude Code auto-loads this into every session, and the skills pick it up. Each user maintains their own — nothing org-specific ships in the repo.

## Share with colleagues

Push this repo to GitHub. Each colleague then:

1. Installs `clockify-mcp` from the shared marketplace on their own computer.
2. Generates their own Clockify key under Profile settings, then API.
3. Runs the local `clockify-mcp --store-key` setup through the guided setup.

The local adapter, skills, and slash commands come from the plugin. Their key
stays in their operating system credential store, and their local adapter calls
Clockify directly only when they use a Clockify tool.

## Tool reference

| Tool | What it does | Notes |
|---|---|---|
| `whoami` | Validate the key. Return user id, default workspace, timezone. | Called only when requested; result is memoised. |
| `list_workspaces` | All workspaces this user belongs to. | |
| `list_projects` | Projects in a workspace. | Cached for `cache_ttl_seconds` (default 5 min). Filter by `name_filter`. |
| `list_tasks` | Tasks inside a project. | |
| `list_tags` | Tags on a workspace. | Cached. |
| `list_time_entries` | The user's entries in a date range. | Single project filter; auto-paginates; returns total hours. |
| `add_time_entry` | Create an entry. | Times accept ISO-8601 or natural language. |
| `update_time_entry` | Edit fields on an entry. | If you pass only one of `start`/`end`, the other is read from the existing entry. |
| `delete_time_entry` | Delete an entry. | Returns `{status: "deleted", entry_id}`. |
| `get_running_timer` | Currently-running entry, or `None`. | |
| `stop_running_timer` | Stop the running entry at a given time. | `end` defaults to `"now"`. |
| `report_summary` | Aggregated totals via the Reports API. | Group by PROJECT / TASK / USER / DAY / WEEK / MONTH / TAG / CLIENT. `only_me=True` restricts to the authenticated user. |
| `report_detailed` | Hydrated entries via the Reports API. | Multi-project / multi-user; use when `list_time_entries` is too limited. |

## Time input formats

Every datetime arg accepts:

| Input | Interpreted as |
|---|---|
| `"2026-05-13T09:30:00Z"` | UTC literal |
| `"2026-05-13T11:30:00+02:00"` | Offset literal |
| `"2026-05-13T09:30:00"` | User's timezone (no offset) |
| `"2026-05-13"` | Midnight in user's timezone |
| `"today 09:30"`, `"yesterday 14:00"` | Day word + HH:MM in user's tz |
| `"09:30"` | Today at HH:MM in user's tz |
| `"2h ago"`, `"45m ago"` | Relative to now |
| `"now"` | Current time |

All values are normalised to UTC `Z` format before being sent to Clockify.

## Legacy HTTP compatibility

The HTTP server remains in the code temporarily for existing remote clients. The
published plugin no longer registers or uses it. New users should use the local
stdio connection above.

The canonical remote MCP URL ends in `/mcp/`. The trailing slash is required:

```text
https://your-service.example/mcp/
```

Existing remote deployments still support dynamic client registration, OAuth
2.1 with PKCE, and stateless JSON responses. This compatibility path is not part
of the published plugin connection and is not recommended for new installs.

### Local smoke test

```bash
export JWT_SIGNING_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export ENCRYPTION_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export PUBLIC_URL=http://localhost:8765
clockify-mcp --http --port 8765 --public-url "$PUBLIC_URL"

# In another terminal:
curl http://localhost:8765/.well-known/oauth-authorization-server | jq
open "http://localhost:8765/authorize?response_type=code&redirect_uri=http://localhost/cb&code_challenge=x&code_challenge_method=plain"
```

Any existing remote client must use the service URL with `/mcp/` appended. Once
all users have upgraded to the local plugin, the remote service and its secrets
can be retired.

## Development

```bash
uv sync --all-groups
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest
```

- src-layout under `src/clockify_mcp/`
- Tests in `tests/` (respx for HTTP mocking, MagicMock for tool-layer tests)
- `clockify_mcp.client.ClockifyClient` is the standalone HTTP wrapper — also usable outside the MCP server (for scripts, automation).

## License

MIT.
