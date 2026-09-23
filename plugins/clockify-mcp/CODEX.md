# Codex host guidance

The skill and workflow bodies, scripts, templates, and assets are shared with
Claude Code. Adapt only the host mechanics:

- Resolve the plugin root from the loaded skill path (two directories above
  the folder containing `SKILL.md`). Replace `${CLAUDE_PLUGIN_ROOT}` in examples
  with that absolute path; do not assume the environment variable exists.
- Treat `$ARGUMENTS` as the user's request, not a literal shell variable.
- Use the available Python interpreter and the current shell's quoting syntax.
- Resolve named skills through the installed plugins and load them before use.
  Claude slash commands are workflow names, not a required Codex UI.
- Discover tools by capability. Tool prefixes differ between hosts; the legacy
  command's `allowed-tools` header is not an authorization grant.
- Use applicable `AGENTS.md` and the user's stated preferences when a workflow
  refers to Claude instructions or memory. Do not edit Claude configuration as
  part of Codex setup. Preserve the shared scripts' existing data locations so
  users can reuse configuration; a `.claude` data path is not a host command.
- Preserve all approval steps. Installation does not authorize account sign-in,
  sending messages, posting time, enabling synchronization, or changing defaults.
- These packages do not register Claude lifecycle hooks. Do not promise automatic
  session-start/stop synchronization in Codex; invoke the documented sync workflow
  explicitly when requested. Report platform-specific limitations honestly.
- Edit the canonical root plugin or `codex/adapters` in the source repository,
  run `scripts/build_codex.py`, and reinstall. Never maintain generated copies
  by hand. A new Codex task loads updated skills and tools.

# Clockify in Codex

- Discover Clockify tools from the connected local plugin and use connected
  calendar tools for calendar reads.
- Preserve the proposal and approval before posting. Both start and end stay on
  quarter-hour boundaries: the shared workflow's universal 15-minute rule takes
  precedence over its older five-minute rounding sentence.
- If the API key is missing, offer the local `uv run clockify-mcp --store-key`
  setup from the plugin README. The user enters their own key in their terminal,
  never in chat. Tool discovery itself must not read a key or contact Clockify.
