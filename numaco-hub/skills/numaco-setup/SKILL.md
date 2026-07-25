---
name: numaco-setup
description: Guided onboarding front door for the Numaco Claude plugin packet. Opens with the privacy and own-accounts promise, confirms automatic updates are enabled, then routes the user through per-plugin setup for whatever they installed (mcp-mail, review-kit, numaco-design, clockify-mcp). Use whenever the user says "set up the numaco plugins", "onboard me", "configure numaco plugins", "numaco setup", or otherwise asks how to get started with the Numaco plugins.
---

# numaco-setup — onboarding front door for the Numaco plugins

This skill walks a new user through getting the Numaco Claude plugin packet
working. It runs once per machine, at the top of the packet, and hands off to
each plugin's own setup for the details. Work through the sections in order.

## 1. Privacy and your own accounts (say this first)

Before configuring anything, make the trust model explicit. Three points:

1. **You configure your own accounts and your own data.** Every plugin in this
   packet acts on accounts and workspaces that you own and connect yourself.
   Nothing is pre-wired to anyone else's data.
2. **Your mail, files, and calendar never pass through a Numaco server.**
   `mcp-mail`, `numaco-design`, and `review-kit` run on the user's machine, or
   talk straight to the user's own provider from that machine. Nobody at Numaco,
   including the author, can see any of it.
3. **`clockify-mcp` is the one exception, and you must say so unprompted.** It
   does not reach Clockify directly. It calls a Numaco-operated MCP server on
   Google Cloud Run, which carries the user's Clockify API key encrypted inside
   their access token and decrypts it in memory on each request to call Clockify.
   It keeps no database of their entries, but the key goes to that server rather
   than into their keychain, and their time entries do pass through it. Say this
   plainly BEFORE offering to connect Clockify, so the choice is informed, and
   mention that the other four plugins can be installed without it.
4. **Where data does travel.** Whatever Claude reads for the user travels to
   Anthropic as part of the conversation, under their own Claude agreement,
   exactly as any file they open in Claude Code does. Beyond that these plugins
   send data only to the providers whose accounts the user connected themselves.
   Their secrets (OAuth tokens, app passwords, API keys) live in the operating
   system's credential store (macOS Keychain, Windows Credential Manager, Linux
   Secret Service), never in plaintext in the repo and never in this chat, with
   the single exception of the Clockify key described above.

Do not disclose, guess, or speculate about which providers or accounts the
author personally uses. This setup is about the user's own accounts only.

## 2. Confirm automatic updates are enabled

New plugin versions should arrive on their own, so the user is never stuck on a
stale build. Turn on auto update for the `numaco` marketplace.

Auto update is a per-user consumer setting under `extraKnownMarketplaces` in the
user's `settings.json`. **Add the `autoUpdate` key to the `numaco` entry that
`claude plugin marketplace add` already created. Never replace that entry, and
never drop its `source` block.** An entry carrying `autoUpdate` without `source`
registers no marketplace at all, which silently disables every Numaco plugin with
no error message shown anywhere.

Read the file, add the one key, write it back. The `numaco` entry should end up
looking like this, with its existing `source` intact:

```json
{
  "extraKnownMarketplaces": {
    "numaco": {
      "source": { "source": "github", "repo": "NumacoAG/claude-plugins" },
      "autoUpdate": true
    }
  }
}
```

Then verify, because this step has two failure modes and only one success mode:
run `claude plugin list` and confirm every Numaco plugin reads `✔ enabled`. If any
reads `✘ disabled`, the entry lost its `source`; re-running
`claude plugin marketplace add NumacoAG/claude-plugins` merges it back and repairs
the install in place. Note that `claude plugin marketplace list` and
`claude plugin marketplace update numaco` both report success even in the broken
state, so neither can be used as the check.

With this on, Claude Code pulls new plugin versions from the `numaco`
marketplace at session start. After an auto update lands, Claude Code prompts you
to run `/reload-plugins` so the new versions become active in the running
session. If you ever want to update on demand instead of waiting for session
start, run `/numaco-update` (from the numaco-hub plugin).

## 3. Route through the plugins the user installed

Ask which plugins the user installed, then set up only those. Each is
independent; do them in any order and pause after each one.

- **mcp-mail** (email across your own providers): run the **mcp-mail-setup**
  skill. It walks you through your own mail accounts provider by provider,
  storing every secret in your OS credential store. Configure only the accounts
  you want; a single account is a valid setup. This release is mail only;
  calendar and Drive are not included yet.
- **review-kit** (markdown co-authoring plus release QA): works out of the box.
  Mobile sync is optional and stays dormant until you opt in: to mirror a doc
  between your laptop and your phone vault, track it with `/dvsync-track`. Until
  you track a doc, nothing is synced anywhere.
- **numaco-design** (branded slide decks, statements of work, reports, and
  timesheets): nothing to preinstall; the renderer toolchain installs itself.
  Preflight the machine by running the renderer doctor from the installed
  plugin:

  ```bash
  python3 "$(ls -dt ~/.claude/plugins/cache/numaco/numaco-design/*/ | head -1)shared/render/numaco_render.py" doctor
  ```

  (If the plugin lives elsewhere, look up the numaco-design `installPath` in
  `~/.claude/plugins/installed_plugins.json` and run
  `python3 <installPath>/shared/render/numaco_render.py doctor`.)

  The doctor installs the Node render dependencies on first run (`npm ci`
  against the committed lockfile) and resolves a browser automatically: it uses
  a system Chrome, Chromium, Edge, or Brave when one exists, and otherwise
  downloads a private `chrome@stable` build into the plugin (about 150 MB, one
  time). The only thing it cannot install by itself is Node.js: if the doctor
  reports Node missing, install it with the platform package manager (macOS:
  `brew install node`; Windows: `winget install OpenJS.NodeJS.LTS`; Linux: the
  distro package, for example `sudo apt-get install nodejs npm`), then rerun
  the doctor. Everything else is automatic; the doctor exits 0 when the machine
  can render.

  Then create your personal defaults file: copy `defaults.toml.example` from
  the numaco-design plugin root to `~/.config/numaco-design/defaults.toml` and
  fill in your rate card and your contact block. The file stays on your machine
  and is never committed anywhere. If you skip this, the SOW skill will ask for
  your rates on first use and offer to write the file for you.
- **clockify-mcp** (time tracking): repeat the hosted-server point from section 1
  first, then set it up. This is **not** an OAuth sign-in. Generate a personal API
  key in Clockify (Profile settings, then API), because the next step asks you to
  paste it and the flow gives you no way to create one mid-stream. On first use the
  plugin sends you to a Numaco-hosted "Connect Clockify" page where you paste that
  key; the server then carries it encrypted in your access token. Only your own
  workspace is ever touched.

## 4. Point at each plugin's own docs for depth

This skill is only the front door. For the full detail of any one plugin, send
the user to that plugin's own documentation:

- **mcp-mail**: its `README.md` and `INSTALL.md` (provider by provider
  walkthrough, troubleshooting, security notes).
- **review-kit**: its `README.md` and the `review-kit` orientation skill.
- **numaco-design**: its `README.md`.
- **clockify-mcp**: its `README.md`.

When a step fails, hand the exact error text back to Claude together with the
plugin and section you were on, and continue from there.
