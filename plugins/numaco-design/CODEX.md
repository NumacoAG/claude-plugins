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

# Using Numaco Design in Codex

Keep the skill's content, brand, review, and approval requirements. Adapt only
the host-specific mechanics below.

- Resolve the plugin root from the loaded skill's path. Replace
  `${CLAUDE_PLUGIN_ROOT}` in examples with that absolute directory; use an
  available Python interpreter and the current shell's quoting syntax.
- An instruction to open a Claude live artifact means an editable budget or
  preview. Use Codex's available visualization capability, a local HTML preview,
  or a table in the conversation. Carry the approved values into the document;
  do not require an unavailable Claude artifact API or invent a commit event.
- Open HTML previews with Codex's file/browser preview capability or the
  operating system's registered browser. `open -a` is a macOS example.
- Keep the final PDF authoritative. On macOS, use the specified CoreGraphics
  verification. On Windows or Linux, rasterize the final PDF with an available
  independent renderer such as Poppler or MuPDF and inspect the pages. State
  that this does not verify macOS Preview fidelity. Do not call `sips` or claim
  a CoreGraphics check passed on an unsupported platform.
- Run the existing build and overflow checks; preserve assets and templates.
  If a build script reports a platform limitation, report it accurately rather
  than changing its commercial content or claiming success.
- Codex uses installed plugin copies. After shared source changes, run the
  repository's `scripts/build_codex.py`; it derives a content-based version.
  Reinstall from the configured marketplace and start a new task.
