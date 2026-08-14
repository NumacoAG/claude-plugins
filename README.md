# Numaco Claude plugins

Numaco AG's public Claude Code plugins, packaged as one marketplace named
`numaco`. Install the ones you want, configure them against your own accounts,
and they stay current on their own. Everything here runs on your machine and
against your own credentials; see the privacy section below.

## What is in the packet

Six plugins ship under the `numaco` marketplace, and all six live in this
repository.

- **numaco-design** (branded output engine). Turns Markdown or a JSON payload
  into Numaco branded, print ready PDFs through one shared renderer and one brand
  core. It carries five model invoked skills: `numaco-report` (reports, memos,
  one-pagers, handovers, solution designs, letters, with a line-items table that
  computes totals), `numaco-sow` (an interactive Statement of Work drafter),
  `numaco-timesheet` (branded timesheets and hours reports, grouped by month,
  hours-only or with computed amounts), `numaco-trading-documents` (quotations,
  order confirmations, delivery notes, and invoices), and `numaco-slide-deck`
  (branded 1920x1080 presentations). Every PDF is verified through CoreGraphics, the
  engine macOS Preview uses, rather than a Chromium preview.
- **review-kit** (markdown co-authoring plus release QA, with mobile sync). Ships
  `obsidian-versioned-review` (the green-mark versioned review loop for
  co-authoring a doc over rounds), `qa-audit` (the release QA log workflow), and a
  folded-in dual-vault-sync engine that reconciles a small tier 1 set of docs
  between your laptop and your phone's iCloud Obsidian vault. The sync stays
  dormant until you track a doc.
- **dev-process-kit** (the specification and acceptance process). The contract
  architecture a project is specified against: what a Tier 1 document is and is
  not, how a project splits into components, the requirement and journey
  identifier scheme with a frozen registry, clause splitting to one testable
  proposition, and the Definition of Done written as complete operator journeys.
  It ships a Python gate that fails closed, and whose first check runs from the
  declared registry to the documents rather than the other way round, so a
  requirement cannot vanish out of the contract while every other check still
  passes. It acts only inside a project you point it at and configures nothing on
  your machine. Review rounds and locks belong to review-kit, which it depends on
  and never restates.
- **mcp-mail** (your own mail, calendar, and files). A self-hosted MCP server
  that gives Claude read and write control across Microsoft 365, Gmail or Google
  Workspace, and any IMAP provider (iCloud, Yahoo, Fastmail, and others). 55
  tools over six surfaces: mail (16), Drive and SharePoint or OneDrive files
  (16), Google Docs (10), calendar (5), Sheets (5), and Slides (3). Search and
  read, send and reply behind a per-message confirmation, drafts, file and
  label, one-click unsubscribe, plus a contacts skill that builds a contact
  directory from your mail history. A single account is a valid setup, and
  calendar and files are opt-in per account: mail alone needs nothing extra,
  while the wider surfaces need a `capabilities` line and a one-off re-consent
  described in INSTALL.md. Files also work with no cloud permissions at all
  against a local iCloud Drive or OneDrive folder.
- **numaco-hub** (front door). The thin starting point: a `numaco-setup` skill
  that onboards you through whatever you installed, and a `/numaco-update` command
  for on-demand updates. Carries no engine of its own.
- **clockify-mcp** (time tracking). Talks to your own Clockify workspace with your
  own authorization to log and reconcile time entries.

## One-time install

You install this packet once per machine. Two commands in a terminal:

```bash
claude plugin marketplace add NumacoAG/claude-plugins
claude plugin install numaco-hub@numaco
```

numaco-hub declares the other five as dependencies, so the second command pulls
numaco-design, review-kit, mcp-mail, clockify-mcp and dev-process-kit in with it
and reports `+ 5 dependencies`. Inside a running Claude Code session the slash forms
`/plugin marketplace add …` and `/plugin install …` do the same thing; the CLI
forms are what a pasted onboarding prompt can actually run.

Check the result, and read this output rather than
`claude plugin marketplace list`, which reports success even when every plugin is
disabled:

```bash
claude plugin list
```

All six should read `✔ enabled`. Then restart Claude Code and say "set up the
numaco plugins" (or "numaco setup") to trigger the `numaco-setup` skill from
numaco-hub. It states the privacy promise, turns on automatic updates, and routes
you through the per-user setup that only you can do: signing in to your own mail
accounts, and generating your own Clockify API key.

If you want only some of the plugins, install those names individually instead,
for example `claude plugin install numaco-design@numaco`.

**Onboarding a colleague.** `numaco-hub/onboarding-paste-prompt.md` is a single
block you can put in an email: the recipient pastes it into Claude Code and it
performs the whole install, the auto-update setting and both local config files,
then hands off to `numaco-setup` for the steps that need the person themselves.
Fill in its `<PLACEHOLDER>` values before sending.

## Privacy

This packet is built so that your data stays yours.

- **You configure your own accounts.** Every plugin acts on accounts and
  workspaces that you own and connect yourself. Nothing is pre-wired to anyone
  else's data.
- **Your mail, files, and calendar never pass through a Numaco server.**
  `mcp-mail`, `numaco-design`, and `review-kit` run entirely on your machine, or
  talk straight to your own provider's API from your machine. Nobody at Numaco,
  including the author, can see any of it.
- **`clockify-mcp` is the one exception, and you should know how it works.** It
  does not talk to Clockify directly. It calls a Numaco-operated MCP server on
  Google Cloud Run, which holds your Clockify API key in encrypted form inside
  your access token and decrypts it in memory on each request in order to call
  Clockify for you. It stores no database of your entries, but the key is handed
  to that server rather than kept in your OS keychain, and your time entries do
  pass through it. Nothing else in the packet works this way. If you would rather
  not use it, install the four engine plugins on their own and skip the hub,
  which currently declares clockify-mcp as a dependency:

  ```bash
  claude plugin marketplace add NumacoAG/claude-plugins
  for p in numaco-design review-kit mcp-mail dev-process-kit; do claude plugin install $p@numaco; done
  ```

  Without numaco-hub you do not get the guided `numaco-setup` skill or the
  `/numaco-update` command, so follow this README instead. Installing
  `numaco-hub` and then uninstalling `clockify-mcp` is not a way around it: the
  hub then fails to load entirely.

- **Where your data does travel.** Whatever Claude reads on your behalf goes to
  Anthropic as part of your conversation, under your own Claude agreement,
  exactly as any file you open in Claude Code does. Beyond that, these plugins
  send your data only to the providers whose accounts you connected yourself
  (your mail host, your Clockify workspace), never to any other destination.
- **Secrets live in your OS keychain.** OAuth tokens, app passwords, and API keys
  go to your operating system's credential store (macOS Keychain, Windows
  Credential Manager, Linux Secret Service), never in plaintext in the repository
  and never in the chat. Local files that could hold secrets (for example
  `accounts.toml` and `.env`) are gitignored. The one exception is the
  `clockify-mcp` API key described above, which lives encrypted in your access
  token instead.

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
- **dev-process-kit**: nothing to configure. Run `/contract-init` inside a
  project's repository when you want to stand up its Tier 1 contract folder;
  until then the plugin is inert. See the plugin's `README.md`.
- **mcp-mail**: run the plugin's `mcp-mail-setup` skill (or read `INSTALL.md`) for
  the provider by provider walkthrough. Configure only the accounts you want;
  every secret goes to your OS credential store. Two local files carry the
  non-secret part: `~/.config/mcp-mail/accounts.toml` (your accounts) and the
  optional `~/.config/mcp-mail/defaults.toml`, which lets a team share one
  Microsoft 365 app registration so nobody has to create an Azure app
  registration of their own.
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
- **dev-process-kit**: Python 3 for the contract gate. No third-party packages.
- **numaco-hub**: no runtime dependencies.
- **clockify-mcp**: nothing to install locally; it talks to a hosted MCP server. See
  the plugin's own `README.md`.

## Layout

```
numaco-claude-plugins/
├── .claude-plugin/
│   └── marketplace.json     the numaco marketplace manifest (six plugins)
├── numaco-design/           branded output engine (reports, SOWs, trading documents, decks)
├── review-kit/              markdown review trio plus dual-vault sync
├── dev-process-kit/         the Tier 1 contract process and its gate
├── mcp-mail/                self-hosted mail MCP server
├── numaco-hub/              front door: setup skill and update command
├── clockify-mcp/            time tracking against your own Clockify workspace
├── LICENSE                  MIT, Numaco AG
└── README.md                this file
```

## Contributing

This repository is public because installing from it should need nothing more
than the marketplace command: no GitHub account, no access request, no auth.
Anyone may fork it and open a pull request.

Nobody but the owner can merge one. `main` carries a ruleset that requires a
pull request with an approving review from a code owner, and
[`.github/CODEOWNERS`](.github/CODEOWNERS) makes the owner the code owner of
every path. The ruleset also blocks force pushes and branch deletion, and holds
every merge until the `publish gate` workflow passes: the privacy scan, the
manifest and version checks, and a clean-config install smoke test.

That gate is the reason the repository can be public at all. It refuses any
change carrying real email addresses, absolute home paths, private keys, or
site-specific terms, and it runs on every pull request, including pull requests
from forks where no local hook of ours can reach. Known-safe matches live in
`.publish-allow`, one path and token per line, each with its reason.

## License

MIT. Copyright (c) 2026 Numaco AG. See [LICENSE](LICENSE).
