---
name: numaco-setup
description: Set up the Numaco plugins in Codex, verify all six plugins, and guide the user through their own optional account configuration. Use for Numaco setup, onboarding, or missing Numaco skills.
---

# Numaco setup in Codex

Read [host guidance](../../CODEX.md). This is the Codex onboarding adapter; the
Claude onboarding skill remains unchanged in the canonical source.

Explain the privacy boundary first: users connect their own accounts, local
adapters talk directly to their providers, and credentials stay in the OS
credential store. Content read into Codex is processed under their OpenAI
agreement, not an Anthropic agreement. Installing does not authorize sign-in,
changing defaults, syncing vaults, or posting time entries.

## Install and verify the packet

Resolve this plugin's root and run with an available Python interpreter:

```text
python "<hub-root>/scripts/codex_packet.py"
```

The helper reads `packet.json`, generated from the shared hub dependency list.
It installs missing, disabled, or changed plugins and verifies all six. Codex
does not install the hub's Claude dependencies automatically.

If the marketplace is missing, register the shared repository first:

```text
codex plugin marketplace add NumacoAG/claude-plugins
```

If `numaco` already points somewhere else, report the source mismatch. Preserve
local changes before an explicit source migration; do not silently replace it.
For a requested local checkout, the helper accepts `--source <checkout-root>`.

The packet exposes 26 native skills: hub 3, design 5, review 7, development
process 6, mail 3, and Clockify 2. There should be no migrated command aliases.
Verify the installed versions and any loading errors. Start a new Codex task
after installation so all new skills and MCP tools are loaded.

## Configure only the requested accounts and features

- Mail: use the installed `mcp-mail-setup` skill. Locate installed plugins with
  `codex plugin list --marketplace numaco --json` or their loaded skill paths,
  not Claude's `installed_plugins.json`.
- Design: keep existing rate and contact defaults. When rendering is requested,
  run the design plugin's `shared/render/numaco_render.py doctor` and follow
  its Codex platform guidance for PDF checks.
- Review/development process: no account setup required. Vault synchronization
  remains opt-in; preserve the user's configured paths. Claude lifecycle hooks
  are not registered in Codex.
- Clockify: discovery exposes tools without reading a key or making a Clockify
  request. If configuration is requested, have the user run
  `uv --directory "<clockify-root>" run clockify-mcp --store-key` in their own
  terminal. Never ask for their API key in chat.

## Update

Use the `numaco-update` skill. Do not apply Claude's `autoUpdate` setting or
`/reload-plugins` to Codex. A Git source needs a marketplace refresh; a local
source only sees its current local files. Never claim a local patch is published.
