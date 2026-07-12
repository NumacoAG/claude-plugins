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
2. **Each plugin runs locally or against your own credentials.** The MCP servers
   and skills run on your machine (or talk straight to your own provider from
   your machine). There is no shared Numaco server sitting in the middle of your
   email, calendar, files, or time entries.
3. **No one else can see your email or your data.** Not the author, not Numaco,
   not any other user. Your secrets (OAuth tokens, app passwords, API keys) live
   in your operating system's credential store (macOS Keychain, Windows
   Credential Manager, Linux Secret Service), never in plaintext in the repo and
   never in this chat.

Do not disclose, guess, or speculate about which providers or accounts the
author personally uses. This setup is about the user's own accounts only.

## 2. Confirm automatic updates are enabled

New plugin versions should arrive on their own, so the user is never stuck on a
stale build. Turn on auto update for the `numaco` marketplace.

Auto update is a per-user consumer setting. It lives under
`extraKnownMarketplaces` in the user's `settings.json`: set `autoUpdate` to
`true` for the `numaco` marketplace entry, for example:

```json
{
  "extraKnownMarketplaces": {
    "numaco": {
      "autoUpdate": true
    }
  }
}
```

With this on, Claude Code pulls new plugin versions from the `numaco`
marketplace at session start. After an auto update lands, Claude Code prompts you
to run `/reload-plugins` so the new versions become active in the running
session. If you ever want to update on demand instead of waiting for session
start, run `/numaco-update` (from the numaco-hub plugin).

## 3. Route through the plugins the user installed

Ask which plugins the user installed, then set up only those. Each is
independent; do them in any order and pause after each one.

- **mcp-mail** (email, calendar, and Drive across your own providers): run the
  **mcp-mail-setup** skill. It walks you through your own mail, calendar, and
  Drive accounts provider by provider, storing every secret in your OS
  credential store. Configure only the accounts you want; a single account is a
  valid setup.
- **review-kit** (markdown co-authoring plus release QA): works out of the box.
  Mobile sync is optional and stays dormant until you opt in: to mirror a doc
  between your laptop and your phone vault, track it with `/dvsync-track`. Until
  you track a doc, nothing is synced anywhere.
- **numaco-design** (branded slide decks, statements of work, and reports): run
  `npm install` in the plugin's `shared/render` directory to install the render
  toolchain, and make sure a Chrome or Chromium browser is installed on the
  machine (the renderer drives it to produce PDFs). Then create your personal
  defaults file: copy `defaults.toml.example` from the numaco-design plugin
  root to `~/.config/numaco-design/defaults.toml` and fill in your rate card
  and your contact block. The file stays on your machine and is never
  committed anywhere. If you skip this, the SOW skill will ask for your rates
  on first use and offer to write the file for you.
- **clockify-mcp** (time tracking): complete the browser OAuth to your own
  Clockify workspace on first use. The plugin talks to Clockify with your own
  authorization; no one else's workspace is involved.

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
