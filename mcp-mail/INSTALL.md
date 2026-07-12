# mcp-mail — installation guide

This guide installs **mcp-mail** on **macOS, Windows, or Linux**. It's written so
you can hand it to Claude ("read INSTALL.md and help me set this up") and have it
walk you through, or follow it yourself. You configure **only the accounts you
want** — there's no requirement to set up all providers.

> **Cross-platform note.** Secrets are stored in your OS credential store
> automatically — macOS **Keychain**, Windows **Credential Manager**, or Linux
> **Secret Service** — via the `keyring` library. The Python server itself is
> identical on every OS; only a few shell commands below differ, and those are
> shown per-platform.

---

## 🤖 If you are Claude reading this to help install

Work through the sections **in order**. Rules for you specifically:

1. **First, determine the user's OS** (ask, or infer from the platform) and use
   the matching command variant throughout — **macOS/Linux** uses a POSIX shell;
   **Windows** uses PowerShell.
2. **Never ask the user to paste a password, client secret, app-specific
   password, or token into the chat.** Secrets go straight into the OS credential
   store via the helper scripts in `server/scripts/`, which read input over
   stdin/`getpass`. Run the script and let the user type into the terminal prompt.
3. The **only** things that go into `accounts.toml` are non-secret IDs (email
   addresses, an Azure client/tenant ID, IMAP host/port). That file is safe to
   read and edit.
4. **Pause after each provider** and confirm it works before moving on. Providers
   are independent.
5. If a step fails, jump to **§9 Troubleshooting** before retrying.

---

## 1. Prerequisites

| Need | Check | Install if missing |
|---|---|---|
| Claude Code | already installed if you're reading this in it | — |
| Python 3.13+ | `python3 --version` (Win: `py --version`) | from python.org, or it comes with `uv` |
| `uv` | `uv --version` | see below |
| `git` | `git --version` | only needed if you `git clone` the repo |

Install `uv`:

- **macOS:** `brew install uv` — or `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Linux:** `curl -LsSf https://astral.sh/uv/install.sh | sh`
- **Windows (PowerShell):** `winget install --id=astral-sh.uv -e`
  — or `powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"`

After installing on Windows, **open a new terminal** so `uv` is on your `PATH`.

---

## 2. Get the code & build the server

Put the repo somewhere stable (you'll point Claude Code's plugin install at this
path). `cd` into it, then build the server's virtual environment:

```bash
cd server
uv sync
cd ..
```

`uv sync` reads `server/uv.lock` and creates an isolated `.venv` — nothing is
installed globally, and on Windows it automatically pulls the credential-store
backend (`pywin32-ctypes`). Re-run it any time dependencies change.

---

## 3. How credentials work (read this once)

mcp-mail splits **identity (non-secret)** from **secrets**:

- **`~/.config/mcp-mail/accounts.toml`** — non-secret: which accounts exist, their
  addresses, the Azure client/tenant ID for M365, IMAP host/port. Safe to edit.
  (On Windows this path resolves to `C:\Users\<you>\.config\mcp-mail\accounts.toml`.)
- **OS credential store** (entries under service name `mcp-mail`) — all secrets:
  the Google OAuth client secret, IMAP app-specific passwords, and the OAuth
  refresh tokens the server caches after you sign in.

What you must store **by hand**, per provider:

| Provider | Store by hand? | What |
|---|---|---|
| Microsoft 365 | **No** | Nothing. The first browser sign-in caches the token automatically. You only put `client_id` + `tenant_id` (non-secret) in the config. |
| Gmail / Workspace | **Yes** | One JSON blob `{"client_id":..., "client_secret":...}` under credential-store account `google-oauth-config`. Shared by all your Google accounts. Per-account refresh tokens are cached automatically after sign-in. |
| iCloud / Yahoo / IMAP | **Yes** | One app-specific password per account, under a credential-store account equal to that account's `id`. |

All entries use **service = `mcp-mail`**. The **account** name defaults to the
account `id` you chose in `accounts.toml` (Google's shared client is the one
exception: account `google-oauth-config`). The helper scripts in §5 handle all of
this for you — you don't need to touch Keychain Access / Credential Manager
directly.

---

## 4. Write your `accounts.toml`

Copy the example and open it.

**macOS / Linux:**
```bash
mkdir -p ~/.config/mcp-mail
cp accounts.toml.example ~/.config/mcp-mail/accounts.toml
${EDITOR:-nano} ~/.config/mcp-mail/accounts.toml      # macOS also: open -e <path>
```

**Windows (PowerShell):**
```powershell
New-Item -ItemType Directory -Force "$HOME\.config\mcp-mail" | Out-Null
Copy-Item accounts.toml.example "$HOME\.config\mcp-mail\accounts.toml"
notepad "$HOME\.config\mcp-mail\accounts.toml"
```

Delete the blocks for providers you don't use. For each account you keep, set a
short `id` (your choice — the handle you'll use in Claude) and the `address`.
Leave M365 `client_id`/`tenant_id` as placeholders for now; you'll fill them in
§5A. **Do not put any secret in this file.**

Validate it parses at any time (network-free, works on every OS):

```bash
cd server
uv run python scripts/check_config.py
cd ..
```

This prints the account ids it parsed, or a clear error if the TOML is malformed.

---

## 5. Set up each provider

Do only the ones you configured. Each is self-contained. The secret-storing
scripts are run the same way on every OS.

### 5A. Microsoft 365 / Outlook

You need an **Azure AD (Microsoft Entra) app registration**. For a work/school
account, your tenant admin may need to approve the permissions.

1. **portal.azure.com → Microsoft Entra ID → App registrations → New registration.**
2. **Name:** anything (e.g. `mcp-mail`). **Supported account types:** "Accounts in
   this organizational directory only" is fine for a single work account.
3. **Redirect URI:** platform **"Mobile and desktop applications"**, URI exactly:
   ```
   http://localhost:8765
   ```
   ⚠️ **No path** — `http://localhost:8765`, not `.../callback`. Must match exactly.
4. **Register**, then from the Overview page copy the **Application (client) ID**
   and **Directory (tenant) ID** into `accounts.toml`:
   ```toml
   client_id = "the Application (client) ID"
   tenant_id = "the Directory (tenant) ID"
   ```
5. **API permissions → Add a permission → Microsoft Graph → Delegated
   permissions**, add: `Mail.ReadWrite`, `Mail.Send`, `MailboxSettings.ReadWrite`,
   `offline_access`. Then **Grant admin consent** if your tenant requires it.
6. **Authentication → Advanced settings → Allow public client flows → Yes.**
   (mcp-mail uses a public client + PKCE; no client secret.)

**No secret to store.** On first use a browser opens for sign-in and the refresh
token is cached automatically.

### 5B. Gmail / Google Workspace

You need a **Google Cloud project** with the Gmail API enabled and one **OAuth
client**. All your Google accounts share this one client.

1. **console.cloud.google.com** → create or select a project.
2. **APIs & Services → Library → Gmail API → Enable.**
3. **APIs & Services → OAuth consent screen:**
   - User type **External** (or **Internal** for a Workspace where you only use
     Workspace accounts). Fill in the app name / support email.
   - **Set publishing status to "In production"** (Publish app). For personal
     self-hosting you can ignore Google's verification requirement — at sign-in
     you'll see an "unverified app" warning you click through
     (Advanced → "Go to … (unsafe)").
   - ⚠️ Leaving it in **Testing** makes Google **expire your refresh token every
     ~7 days**. Production avoids weekly re-auth.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID →
   Application type: Desktop app.** Copy the **Client ID** and **Client secret**.
5. Store the client in the credential store (shared by all your Google accounts):

   ```bash
   cd server
   uv run python scripts/store_google_oauth.py
   cd ..
   ```

   Paste the client_id and client_secret at the prompts (the secret is hidden and
   never echoed into chat or shell history).

Each Gmail account's refresh token is cached automatically on first sign-in.

### 5C. iCloud / Yahoo / other IMAP

You need an **app-specific password** per IMAP account (your normal login password
won't work over IMAP with 2FA on).

- **iCloud:** appleid.apple.com → **Sign-In and Security → App-Specific Passwords →
  Generate** (requires 2FA). Host/port already in the example
  (`imap.mail.me.com:993` / `smtp.mail.me.com:587`).
- **Yahoo:** Yahoo Account → **Account Security → Generate app password**. Host/port
  `imap.mail.yahoo.com:993` / `smtp.mail.yahoo.com:587`. (Yahoo tightens security
  often; if it stops working, regenerate.)
- **Other IMAP (Fastmail, etc.):** generate an app password; set host/port in
  `accounts.toml`.

Store each app-specific password (run **once per IMAP account**):

```bash
cd server
uv run python scripts/store_imap_password.py
cd ..
```

It asks for the account id (must match `accounts.toml` exactly) and the password
(hidden prompt — not shown on screen or saved to history).

---

## 6. Install the plugin in Claude Code

In a Claude Code session, install from the public Numaco marketplace:

```
/plugin marketplace add NumacoAG/claude-plugins
/plugin install mcp-mail@numaco
```

If you are instead working from a local copy of this folder, register that folder
as a marketplace with its **absolute path**:

```
/plugin marketplace add /absolute/path/to/mcp-mail
/plugin install mcp-mail@numaco
```

(Windows: either slash style works in the path.)

Then **restart your Claude Code session**.

> CLI equivalents: `claude plugin marketplace add NumacoAG/claude-plugins` then
> `claude plugin install mcp-mail@numaco`.

The manifest registers the MCP server automatically using
`${CLAUDE_PLUGIN_ROOT}/server` (resolved to wherever the plugin is installed) —
you do **not** edit `settings.json` by hand. The server is launched as
`uv --directory <plugin>/server run python -m mcp_mail`, so `uv` must be on your
`PATH` (it is, after §1).

---

## 7. First run & sign-in

In Claude, start with the no-network call:

> **"List my mail accounts."**

This calls `mail_list_accounts` and echoes back the accounts from `accounts.toml`.
No browser, no auth yet.

Then exercise one account so OAuth runs (use one of your ids):

> **"List the folders in my work-m365 account."**

- **Microsoft:** a browser opens to sign in; the redirect lands on
  `http://localhost:8765`; the token is cached.
- **Gmail:** a browser opens for Google consent on `http://localhost:8766`. On the
  "unverified app" screen choose **Advanced → Go to … (unsafe)** and approve.
- **IMAP:** no browser — it logs in with the stored app-specific password.

**First-run prompts to expect:**
- **macOS:** a Keychain prompt the first time the server reads/writes an entry —
  choose **Always Allow**.
- **Windows:** Windows Defender Firewall may ask to allow Python to listen on the
  loopback port (8765/8766) during sign-in — **Allow access** (Private networks is
  enough; it's localhost-only).

---

## 8. Smoke test

Ask Claude to run a few primitives (adjust ids to yours):

1. "List unread messages across all my accounts, newest first."
2. "Read the latest message in my personal-gmail inbox."
3. "Search my work-m365 account for messages from `someone@example.com`."
4. (optional) "Draft a reply to that thread" — **send/reply pause for your
   confirmation**; nothing leaves your mailbox until you approve.

To build a contact directory, run **`/contacts`** (see `skills/contacts/SKILL.md`;
set its `OUTPUT_PATH` first).

---

## 9. Troubleshooting

| Symptom | Fix |
|---|---|
| `No accounts config at …` | Create `~/.config/mcp-mail/accounts.toml` (§4). |
| `uv: command not found` / not recognized | Install `uv` (§1); on Windows open a **new** terminal so PATH updates. |
| M365 sign-in fails / "redirect URI mismatch" | Azure redirect URI must be **exactly** `http://localhost:8765` (no path), platform **Mobile and desktop applications**; enable **Allow public client flows** (§5A.6). |
| M365 "need admin approval" | Tenant requires admin consent for the Graph permissions — ask your admin (§5A.5). |
| Google "Access blocked: app not verified" | Publish the consent screen to Production, or add yourself as a Test user; then **Advanced → Go to … (unsafe)**. |
| Gmail dies after ~a week | Consent screen still in **Testing** (7-day token expiry). Set to **Production** (§5B.3) and re-authorize once. |
| `OAuth client config not found in Keychain` | Run `scripts/store_google_oauth.py` (§5B.5). |
| `No app-specific password in Keychain for '<id>'` | Run `scripts/store_imap_password.py` for that id (§5C); the id must match `accounts.toml`. |
| IMAP login fails | Regenerate the app-specific password; confirm 2FA is on; check host/port. |
| Browser sign-in hangs (Windows) | Allow Python through Windows Firewall for the loopback port; close anything else using 8765/8766. |
| `Address already in use` on :8765 / :8766 | Another process (or a stuck prior auth) holds the port; close it and retry. |
| Plugin tools don't appear | Restart the Claude Code session after install; confirm with `/plugin` that `mcp-mail` is enabled. |
| See the raw server error | Run standalone: `cd server` then `uv run python -m mcp_mail` (stdio server; Ctrl-C to stop). |

---

## 10. Security notes

- All secrets live in the OS credential store (service `mcp-mail`) — macOS
  Keychain, Windows Credential Manager, or Linux Secret Service. Nothing secret is
  written to `accounts.toml` or any file in the repo.
- The setup scripts read secrets via stdin/`getpass`, so they don't land in your
  shell history.
- The server binds to `localhost` and is only spoken to by Claude Code over stdio.
- `mail_send` / `mail_reply` always require a per-message confirmation.
  `mail_delete` does **not** — be deliberate before allowlisting it.
- To revoke later: delete the credential-store entries (macOS **Keychain Access** →
  search `mcp-mail`; Windows **Credential Manager** → Windows Credentials; Linux
  **Seahorse**/secret-tool), and/or revoke the app at the provider (Azure AD app,
  Google account permissions, Apple ID app-specific passwords, Yahoo security).

---

You're set. Hand any failures back to Claude with the exact error text and the
section number you were on.
