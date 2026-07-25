# Numaco Claude plugins

Numaco AG's public Claude Code plugins, packaged as one marketplace named
`numaco`. Install the ones you want, configure them against your own accounts,
and they stay current on their own. Everything here runs on your machine and
against your own credentials; see the privacy section below.

## What is in the packet

Five plugins ship under the `numaco` marketplace. Four live in this repository;
`clockify-mcp` is referenced from its own GitHub repository.

- **numaco-design** (branded output engine). Turns Markdown or a JSON payload
  into Numaco branded, print ready PDFs through one shared renderer and one brand
  core. It carries four model invoked skills: `numaco-report` (reports, memos,
  one-pagers, handovers, solution designs, letters, with a line-items table that
  computes totals), `numaco-sow` (an interactive Statement of Work drafter),
  `numaco-timesheet` (branded timesheets and hours reports, grouped by month,
  hours-only or with computed amounts), and `numaco-slide-deck` (branded
  1920x1080 presentations). Every PDF is verified through CoreGraphics, the
  engine macOS Preview uses, rather than a Chromium preview.
- **review-kit** (markdown co-authoring plus release QA, with mobile sync). Ships
  `obsidian-versioned-review` (the green-mark versioned review loop for
  co-authoring a doc over rounds), `qa-audit` (the release QA log workflow), and a
  folded-in dual-vault-sync engine that reconciles a small tier 1 set of docs
  between your laptop and your phone's iCloud Obsidian vault. The sync stays
  dormant until you track a doc.
- **mcp-mail** (your own email). A self-hosted MCP server
  that gives Claude read and write control over your mail across Microsoft 365,
  Gmail or Google Workspace, and any IMAP provider (iCloud, Yahoo, Fastmail, and
  others). Search and read, send and reply behind a per-message confirmation,
  file and label, one-click unsubscribe, plus a `/contacts` skill that builds a
  contact directory from your mail history. A single account is a valid setup.
  This release ships mail only (14 tools). Calendar and Drive are not included
  yet.
- **numaco-hub** (front door). The thin starting point: a `numaco-setup` skill
  that onboards you through whatever you installed, and a `/numaco-update` command
  for on-demand updates. Carries no engine of its own.
- **clockify-mcp** (time tracking). Talks to your own Clockify workspace with your
  own authorization to log and reconcile time entries. Sourced from
  `NumacoAG/clockify-mcp` on GitHub.

## One-time install

You install this packet once per machine. Paste the following into Claude Code.

1. Add the marketplace:

   ```
   /plugin marketplace add NumacoAG/claude-plugins
   ```

2. Install the packet with one command. numaco-hub declares the other four as
   dependencies, so this pulls numaco-design, review-kit, mcp-mail, and
   clockify-mcp in with it:

   ```
   /plugin install numaco-hub@numaco
   ```

   If you want only some of them, install those names individually instead, for
   example `/plugin install numaco-design@numaco`.

3. Run the guided setup. Say "set up the numaco plugins" (or "numaco setup") to
   trigger the `numaco-setup` skill from numaco-hub. It states the privacy
   promise, confirms automatic updates are enabled, and routes you through
   per-plugin setup for exactly what you installed.

## Privacy

This packet is built so that your data stays yours.

- **You configure your own accounts.** Every plugin acts on accounts and
  workspaces that you own and connect yourself. Nothing is pre-wired to anyone
  else's data.
- **Each plugin runs locally or against your own credentials.** The MCP servers
  and skills run on your machine, or talk straight to your own provider's API from
  your machine. There is no shared Numaco server sitting between you and your
  email, calendar, files, or time entries.
- **No one at Numaco can see your mail or your data.** Not the author, not
  Numaco, not any other user of these plugins: nothing in this packet opens a
  channel that would carry your data to them. Be clear about the one place it
  does travel: whatever Claude reads on your behalf goes to Anthropic as part of
  your conversation, under your own Claude agreement, exactly as any file you
  open in Claude Code does. These plugins send your data nowhere else.
- **Secrets live in your OS keychain.** OAuth tokens, app passwords, and API keys
  go to your operating system's credential store (macOS Keychain, Windows
  Credential Manager, Linux Secret Service), never in plaintext in the repository
  and never in the chat. Local files that could hold secrets (for example
  `accounts.toml` and `.env`) are gitignored.

## Updates

New plugin versions arrive on their own once you enable auto update for the
`numaco` marketplace, so you are never stuck on a stale build.

- **Automatic (recommended).** With auto update on, Claude Code pulls new plugin
  versions from the `numaco` marketplace at session start, then prompts you to run
  `/reload-plugins` so the new versions become active in the running session. As a
  publisher you push a version bump; colleagues on auto update receive it at their
  next session start.
- **Enable auto update.** Auto update is a per-user setting under
  `extraKnownMarketplaces` in your `settings.json`. Step 1 already created the
  `numaco` entry together with its `source` block, so add the `autoUpdate` key
  beside `source` rather than replacing the entry. The result should look like
  this:

  ```json
  {
    "extraKnownMarketplaces": {
      "numaco": {
        "source": {
          "source": "github",
          "repo": "NumacoAG/claude-plugins"
        },
        "autoUpdate": true
      }
    }
  }
  ```

  An entry that carries `autoUpdate` but no `source` registers no marketplace at
  all, so keep the `source` block.

  The `numaco-setup` skill turns this on for you during onboarding.
- **Manual (on demand).** To update right now instead of waiting for the next
  session start, refresh the marketplace and reload:

  ```
  /plugin marketplace update numaco
  /reload-plugins
  ```

  The `/numaco-update` command from numaco-hub runs exactly these two steps and
  shows how to check installed versions.
- **Publishing an update.** Bump the `version` field in the plugin's
  `.claude-plugin/plugin.json`, update the matching `version` in this repository's
  `.claude-plugin/marketplace.json`, commit, and push. Everyone on auto update
  picks it up at their next session start.

## Per-plugin setup

- **numaco-hub**: nothing to configure. Run its `numaco-setup` skill first; it
  orchestrates everything below.
- **numaco-design**: nothing to preinstall; the renderer toolchain installs
  itself on first use. The guided setup runs the renderer doctor
  (`python3 shared/render/numaco_render.py doctor` inside the plugin), which
  installs the Node dependencies and finds or downloads a browser automatically.
  See the plugin's `README.md`.
- **review-kit**: works out of the box. Mobile sync stays dormant until you opt in:
  track a doc with `/dvsync-track` to mirror it between your laptop and your phone
  vault. See the plugin's `README.md` and its orientation skill.
- **mcp-mail**: run the plugin's `mcp-mail-setup` skill (or read `INSTALL.md`) for
  the provider by provider walkthrough. Configure only the accounts you want;
  every secret goes to your OS credential store.
- **clockify-mcp**: complete the browser OAuth to your own Clockify workspace on
  first use. See the plugin's `README.md`.

## Runtime dependencies

Install these on the machine for the plugins you use.

- **numaco-design**: Claude Code, signed in. The guided setup (or the first
  render) installs the renderer dependencies automatically, including a private
  Chrome build if no browser is found. Node 18 or newer is installed via your
  package manager if absent (the renderer prints the exact command and you
  rerun). Python 3.11 or newer for the build engines (standard library only). The
  PDF fidelity check is macOS only; rendering itself is cross-platform.
- **mcp-mail**: Python 3.13 or newer and [`uv`](https://docs.astral.sh/uv/), plus
  provider authentication (Microsoft or Google OAuth, or an IMAP app password) for
  each account you connect.
- **review-kit**: Python 3 for the review and sync scripts. No third-party
  packages.
- **numaco-hub**: no runtime dependencies.
- **clockify-mcp**: see its own repository.

## Layout

```
numaco-claude-plugins/
├── .claude-plugin/
│   └── marketplace.json     the numaco marketplace manifest (five plugins)
├── numaco-design/           branded output engine (reports, SOWs, decks)
├── review-kit/              markdown review trio plus dual-vault sync
├── mcp-mail/                self-hosted mail MCP server
├── numaco-hub/              front door: setup skill and update command
├── LICENSE                  MIT, Numaco AG
└── README.md                this file
```

clockify-mcp is not vendored here; the marketplace references it from
`NumacoAG/clockify-mcp` on GitHub.

## License

MIT. Copyright (c) 2026 Numaco AG. See [LICENSE](LICENSE).
