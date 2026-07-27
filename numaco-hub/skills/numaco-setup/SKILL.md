---
name: numaco-setup
description: Guided onboarding front door for the Numaco Claude plugin packet. Opens with the privacy and own-accounts promise, confirms the install and automatic updates, then routes the user through the per-user setup that only they can do (their own mail sign-in, their own Clockify API key, their own rate card). Use whenever the user says "set up the numaco plugins", "onboard me", "configure numaco plugins", "numaco setup", or otherwise asks how to get started with the Numaco plugins.
---

# numaco-setup, onboarding front door for the Numaco plugins

This skill walks a user through getting the Numaco Claude plugin packet working.
It runs once per machine, at the top of the packet, and hands off to each
plugin's own setup for the details. Work through the sections in order.

Some users arrive here having already run the one-paste onboarding prompt from
their onboarding email, which does sections 2 and 3 for them. Check before
redoing that work: run `claude plugin list` and look for the two config files in
section 3. Sections 4 and 5 always apply, because they are the parts no script
can do on someone else's behalf.

## 1. Privacy and your own accounts (say this first)

Before configuring anything, make the trust model explicit. Four points:

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
   plainly BEFORE offering to connect Clockify, so the choice is informed. If
   they would rather not use it, the honest answer is that the three engine
   plugins (`numaco-design`, `review-kit`, `mcp-mail`) install and work fine on
   their own, but they have to skip `numaco-hub` as well, because the hub
   declares `clockify-mcp` as a dependency and fails to load without it. Do not
   tell them they can install the other four and drop this one: uninstalling
   `clockify-mcp` afterwards takes this skill and `/numaco-update` offline.
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

## 2. Confirm the install, then turn on automatic updates

**Install (skip if `claude plugin list` already shows the packet).** Two
commands, in this order:

```bash
claude plugin marketplace add NumacoAG/claude-plugins
claude plugin install numaco-hub@numaco
```

The second reports `+ 4 dependencies: numaco-design, review-kit, mcp-mail,
clockify-mcp`. Run these as shell commands. The `/plugin ...` slash forms do the
same thing when a person types them, but they cannot be executed from a pasted
prompt.

**Automatic updates.** New plugin versions should arrive on their own, so the
user is never stuck on a stale build. Auto update is a per-user setting under
`extraKnownMarketplaces` in the user's `settings.json` (the file inside
`$CLAUDE_CONFIG_DIR` when that variable is set, otherwise `~/.claude`).

**Add the `autoUpdate` key to the `numaco` entry that
`claude plugin marketplace add` already created. Never replace that entry, and
never drop its `source` block.** Read the file, parse it as JSON, set
`extraKnownMarketplaces.numaco.autoUpdate` to `true`, write the whole object
back, and change nothing else. Never write this file from a template. An entry
carrying `autoUpdate` without `source` registers no marketplace at all, which
silently disables every Numaco plugin with no error message shown anywhere.

The `numaco` entry should end up looking like this, with its existing `source`
intact:

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
`claude plugin marketplace add NumacoAG/claude-plugins` merges it back, preserves
`autoUpdate`, and repairs the install in place. Note that
`claude plugin marketplace list` and `claude plugin marketplace update numaco`
both report success even in the broken state, so neither can be used as the
check.

With this on, Claude Code pulls new plugin versions from the `numaco`
marketplace at session start. After an auto update lands, Claude Code prompts you
to run `/reload-plugins` so the new versions become active in the running
session. If you ever want to update on demand instead of waiting for session
start, run `/numaco-update` (from the numaco-hub plugin).

One thing auto update does not do: it never touches the two local config files in
section 3. A new rate card, or a change of Microsoft 365 app registration, still
arrives by email and is pasted in by hand.

## 3. The two local config files

Both are plain text on the user's own machine, both hold non-secret settings
only, and neither belongs in any repository. If a file already exists, show its
current contents and ask before changing it. Never overwrite silently.

- **`~/.config/numaco-design/defaults.toml`** (rate card and contact block).
  Copy `defaults.toml.example` from the numaco-design plugin root and fill it in.
  It holds a `[sow]` table (`list_rate_chf_per_hour`, `standard_discount_pct`,
  `payment_days`) and two `[[sow.contacts]]` entries, each with `name`, `role`
  and `email`. The contacts are read at render time by the SOW build script, and
  the second one is the default consultant on a timesheet; the rate keys are read
  by the SOW skill conversation. Skipping this file is allowed: the SOW skill
  will ask for the rates on first use and offer to write the file.
- **`~/.config/mcp-mail/accounts.toml`**, plus the optional
  **`~/.config/mcp-mail/defaults.toml`**. The first describes the user's own mail
  accounts. The second is where a shared Microsoft 365 app registration lives, as
  a `[m365]` table with `client_id` and `tenant_id`. When those two values are
  supplied (they come in the onboarding email), the user skips the whole Azure
  portal section of INSTALL.md: no app registration to create, no admin consent
  to chase. They are application identity, not credentials, so a config file is
  the right place for them, and they authorise nothing on their own. They should
  still stay inside the organisation that issued them. Anything set per account
  in `accounts.toml` overrides the shared file key by key, so registering a
  private Azure app later stays possible.

If `accounts.toml` already exists, append a new account block and leave the
existing ones untouched. Rewriting the file would break the user's other accounts
and orphan their credential-store entries.

## 4. Route through the plugins the user installed

Ask which plugins the user installed, then set up only those. Each is
independent; do them in any order and pause after each one.

- **mcp-mail** (mail, calendar, and files across your own providers): run the
  **mcp-mail-setup** skill. It walks you through your own accounts provider by
  provider, storing every secret in your OS credential store.

  **Before that skill reaches the Microsoft step, ask the gate question:** *"Did
  your organisation give you a `client_id` and a `tenant_id` for mcp-mail?"* At
  Numaco the answer is yes and the two values arrive in the onboarding email;
  they go into the `[m365]` table of `~/.config/mcp-mail/defaults.toml` (section
  3 above) and the Azure portal never enters the picture. If the user does not
  have them, tell them to ask for them rather than registering their own app: on
  a managed tenant a self-registered app returns `access_denied` at the consent
  screen, and every duplicate registration made that way is one more dead app in
  the directory. This is the single most common way this install fails. Configure only the
  accounts you want; a single account is a valid setup. The build ships 55 tools
  over six surfaces: mail (16), Drive and SharePoint or OneDrive files (16),
  Google Docs (10), calendar (5), Sheets (5) and Slides (3). Mail works on its
  own with nothing extra. Calendar and files are opt-in per account: each account
  declares a `capabilities` list, and M365 and Google additionally need a one-off
  re-consent so the cached token carries the wider scopes. Warn the user about
  one thing specifically: on Google the wider scopes travel in the same list as
  mail, so anyone upgrading from a mail-only release must run
  `scripts/reauth_google.py <account-id>` once per Google account or mail itself
  stops working. On Microsoft 365 there is no such risk, and the equivalent
  `scripts/reauth_m365.py` is purely optional. If the tenant blocks the
  SharePoint permission, point them at the local filesystem backend in
  INSTALL.md section 5E, which needs no permissions. The mail tools appear only
  after a Claude Code restart.
- **review-kit** (markdown co-authoring plus release QA): works out of the box.
  Mobile sync is optional and stays dormant until you opt in: to mirror a doc
  between your laptop and your phone vault, track it with `/dvsync-track`. Until
  you track a doc, nothing is synced anywhere.
- **numaco-design** (branded slide decks, statements of work, reports, and
  timesheets): nothing to preinstall; the renderer toolchain installs itself.
  Preflight the machine by running the renderer doctor from the installed
  plugin. Resolve the path from the manifest rather than guessing it, so this
  works whatever `CLAUDE_CONFIG_DIR` is set to:

  ```bash
  DESIGN=$(python3 -c "import json,os;p=os.path.expanduser(os.environ.get('CLAUDE_CONFIG_DIR','~/.claude')+'/plugins/installed_plugins.json');print(json.load(open(p))['plugins']['numaco-design@numaco'][0]['installPath'])")
  python3 "$DESIGN/shared/render/numaco_render.py" doctor
  ```

  (Fallback if that manifest is not where you expect it: the plugin cache is laid
  out as `plugins/cache/<marketplace>/<plugin>/<version>/`, so
  `ls -dt ~/.claude/plugins/cache/numaco/numaco-design/*/` finds the newest copy.)

  The doctor installs the Node render dependencies on first run (`npm ci`
  against the committed lockfile) and resolves a browser automatically: it uses
  a system Chrome, Chromium, Edge, or Brave when one exists, and otherwise
  downloads a private `chrome@stable` build into the plugin (about 150 MB, one
  time). The only thing it cannot install by itself is Node.js: if the doctor
  reports Node missing, install it with the platform package manager (macOS:
  `brew install node`; Windows: `winget install OpenJS.NodeJS.LTS`; Linux: the
  distro package, for example `sudo apt-get install nodejs npm`), then rerun
  the doctor. Everything else is automatic; the doctor exits 0 when the machine
  can render. Then make sure the defaults file from section 3 is in place.
- **clockify-mcp** (time tracking): repeat the hosted-server point from section 1
  first, then set it up. **The user generates their own Clockify API key, and
  nobody else's key will do.** A Clockify API key authenticates as the person who
  owns it: entries filed with a colleague's key land under that colleague's name,
  on their timesheet, against their approvals. Generate it in Clockify under
  Profile settings, then API, before starting the connect flow, because the flow
  gives no way to create one mid-stream. It is an OAuth flow, but with a twist
  worth naming: instead of signing in to Clockify, the user pastes that key into
  a Numaco-hosted "Connect Clockify" page, and the server then carries it
  encrypted in the access token. Only their own workspace is ever touched.

## 5. What is left for the user, and why nobody can do it for them

Name these explicitly at the end, so nothing is silently skipped. Each one
requires the person themselves:

- **Signing in to each mail account.** The first mail call opens a browser on
  `http://localhost:8765` (Microsoft) or `http://localhost:8766` (Google). Only
  the account owner can authenticate, and the resulting refresh token is written
  to their own credential store.
- **A Google OAuth client, if they want Gmail or Workspace.** It carries a client
  secret and therefore ships in nobody's config: they create it in their own
  Google Cloud project and store it with `scripts/store_google_oauth.py`.
- **An app-specific password per IMAP account** (iCloud, Yahoo, Fastmail), stored
  with `scripts/store_imap_password.py`. Generated at the provider, by them.
- **Their own Clockify API key**, for the reason in section 4.
- **A Claude Code restart** after the install, before the mail tools appear.
- **Approving the file writes and shell commands** this setup performs. Claude
  asks per action, by design.

## 6. Point at each plugin's own docs for depth

This skill is only the front door. For the full detail of any one plugin, send
the user to that plugin's own documentation:

- **mcp-mail**: its `README.md` and `INSTALL.md` (provider by provider
  walkthrough, troubleshooting, security notes).
- **review-kit**: its `README.md` and the `review-kit` orientation skill.
- **numaco-design**: its `README.md`.
- **clockify-mcp**: its `README.md`.

When a step fails, hand the exact error text back to Claude together with the
plugin and section you were on, and continue from there.
