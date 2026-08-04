# One-paste onboarding prompt

This is the block you send a colleague. They open Claude Code, paste it once, and
Claude performs the whole machine-side install: the two install commands, the
auto-update setting, and both local config files. What is left afterwards is only
what the person has to do in their own name (sign in to their own mailbox,
generate their own Clockify API key), and `numaco-setup` walks them through that.

## Before you send it

Replace every `<PLACEHOLDER>` with the recipient's values. They come from the
sender's own private configuration and are deliberately absent from this
repository:

| Placeholder | Value |
|---|---|
| `<RATE-CHF-PER-HOUR>` | list rate, a number, no quotes |
| `<DISCOUNT-PCT>` | standard discount percent, a number |
| `<PAYMENT-DAYS>` | payment terms in days, a number |
| `<CONTACT-1-NAME>`, `<CONTACT-1-ROLE>`, `<CONTACT-1-EMAIL>` | first supplier contact printed in every SOW |
| `<CONTACT-2-NAME>`, `<CONTACT-2-ROLE>`, `<CONTACT-2-EMAIL>` | second contact, also the default consultant on timesheets, normally the recipient |
| `<YOUR-WORK-EMAIL>` | the recipient's own work mailbox |
| `<M365-CLIENT-ID>`, `<M365-TENANT-ID>` | the shared Microsoft 365 app registration |

Two rules for the email itself. Send it only to addresses inside your own
organisation, because it carries your real rate card. And tell the recipient not
to paste it into a shared or logged session, for the same reason. The Microsoft
365 client id and tenant id are application identity rather than secrets (a
public client transmits the client id in the browser URL on every sign-in, and a
tenant id resolves from Microsoft's unauthenticated discovery endpoint), so they
are safe in a config file, but they still belong inside the organisation that
issued them: one shared app registration means one shared blast radius, since its
consented Graph scopes apply to everyone who signs in through it.

No password, refresh token, app password or Clockify key ever goes into this
email. The prompt never asks for one either.

## The prompt

```
You are setting me up with the Numaco Claude plugins. Work through steps 0 to 6
in order, running the commands yourself with Bash. Show me the output of each
command. If any step fails, stop and tell me the step number and the exact error
text rather than improvising a workaround.

Two things I should expect: you will ask my permission for each command and for
each file you write outside this folder, and approving them is the normal course
of this setup. You will never ask me to paste a password, a token or an API key
into this chat, and I should refuse if anything ever does.

One rule that overrides everything below. This prompt was sent to me with real
values filled in. If any angle-bracket placeholder is still present when you
reach the step that would write it (anything shaped like <RATE-CHF-PER-HOUR> or
<M365-CLIENT-ID>), do NOT write that file, do NOT invent a value, and do NOT
leave the placeholder in place. Stop, tell me exactly which placeholder is
missing, and tell me to ask the person who sent me this prompt for it. A config
file containing a placeholder fails silently later: the document generator will
print it onto a real customer document, and a placeholder client id simply cannot
sign in.

STEP 0, preflight. Assume I have NOTHING installed beyond Claude Code itself: no
Homebrew, no Node, no uv. Never tell me to run "brew" unless "brew --version"
already succeeds, because installing Homebrew is a long detour that needs Xcode
command line tools and an admin password.

Report my operating system, then check the toolchain:
  claude --version
  python3 --version
  uv --version
  node --version

uv is required: mcp-mail cannot start without it. If it is missing, install it:
  macOS and Linux:  curl -LsSf https://astral.sh/uv/install.sh | sh
  Windows:          winget install --id=astral-sh.uv -e
That installer puts uv in ~/.local/bin and edits my shell profile, which only
affects NEW terminals. So do not re-check with a bare "uv --version", which will
still fail in this session and look like the install did not work. Re-check with
the full path and then put it on the path for the rest of this session:
  "$HOME/.local/bin/uv" --version
  export PATH="$HOME/.local/bin:$PATH"

Python must be 3.11 or newer, and this is a HARD requirement, not advice. On 3.9
or 3.10 the document generator silently ignores the settings file you write in
STEP 3 and prints placeholder contact details onto real customer documents, with
no error shown. Read the version number and compare it properly. If it is below
3.11, install a newer one WITHOUT Homebrew, then re-check:
  macOS:    download the current macOS 64-bit universal2 installer from
            python.org/downloads and run it (a normal double-click installer),
            or, now that uv exists: uv python install 3.13
  Windows:  winget install --id=Python.Python.3.13 -e
  Linux:    the distro package, for example: sudo apt-get install python3.13
Node is needed later, for slide decks and PDF documents only. If it is missing,
say so now and tell me I will need it before my first document, and that the
no-Homebrew route is the Node LTS installer from nodejs.org (again a normal
double-click installer). Do not claim a later step installs it, because none does.

Do not continue until claude reports a version, uv reports a version, and python3
reports 3.11 or newer.

STEP 1, install the packet. Exactly these two commands, in this order:
  claude plugin marketplace add NumacoAG/claude-plugins
  claude plugin install numaco-hub@numaco
The second should report "+ 5 dependencies: numaco-design, review-kit, mcp-mail,
clockify-mcp, dev-process-kit". Then run "claude plugin list" and confirm six
plugins are present and each one reads enabled.

STEP 2, turn on automatic updates by MERGING one key.
The target file is settings.json inside $CLAUDE_CONFIG_DIR when that variable is
set, otherwise ~/.claude/settings.json. Read it, parse it as JSON, set
extraKnownMarketplaces.numaco.autoUpdate to true, write the whole object back,
and change nothing else. Do not write this file from a template and do not
replace the numaco entry. Step 1 created that entry with a "source" block, and an
entry that carries autoUpdate without source registers no marketplace at all,
which silently disables every plugin with no error shown anywhere. The correct
end state is:
  "numaco": {
    "source": { "source": "github", "repo": "NumacoAG/claude-plugins" },
    "autoUpdate": true
  }
Then run "claude plugin list" again and confirm all six still read enabled. Do
not use "claude plugin marketplace list" as the check: it reports success even
when everything is disabled. If any plugin now reads disabled, repair it by
re-running "claude plugin marketplace add NumacoAG/claude-plugins", which merges
"source" back and keeps autoUpdate, then verify again.

STEP 3, write my numaco-design defaults (rate card and contacts).
Run: mkdir -p ~/.config/numaco-design
If ~/.config/numaco-design/defaults.toml already exists, show me its contents and
ask before changing anything. Otherwise create it with exactly this content:

[sow]
list_rate_chf_per_hour = <RATE-CHF-PER-HOUR>
standard_discount_pct = <DISCOUNT-PCT>
payment_days = <PAYMENT-DAYS>

[[sow.contacts]]
name = "<CONTACT-1-NAME>"
role = "<CONTACT-1-ROLE>"
email = "<CONTACT-1-EMAIL>"

[[sow.contacts]]
name = "<CONTACT-2-NAME>"
role = "<CONTACT-2-ROLE>"
email = "<CONTACT-2-EMAIL>"

Tell me what this file feeds: the two contacts are printed in the Parties block
of every statement of work, the second one is also the default consultant on a
timesheet, and the three rate keys are what the SOW skill quotes from. This file
is private to my machine and belongs in no repository.

STEP 4, write my mcp-mail configuration.
Run: mkdir -p ~/.config/mcp-mail
(a) Shared Microsoft 365 app identity. If ~/.config/mcp-mail/defaults.toml
already exists, show it to me and ask before changing it. Otherwise create it
with exactly:

[m365]
client_id = "<M365-CLIENT-ID>"
tenant_id = "<M365-TENANT-ID>"

Explain, in one or two sentences, that these two values are application identity
and not secrets: they say which application is asking, they authorise nothing on
their own, and my own browser sign-in in step 6 is what grants access. They stay
inside the company: never in a repository, never in a chat with anyone outside
it.

(b) My accounts. If ~/.config/mcp-mail/accounts.toml already exists, APPEND the
account block below and leave every existing account exactly as it is; do not
rewrite the file, because that would break my other accounts and orphan their
entries in the credential store. If it does not exist, create it with the block
plus the commented presets:

[[account]]
id = "work-m365"
provider = "m365"
address = "<YOUR-WORK-EMAIL>"
auto_send = false
capabilities = ["mail", "calendar", "drive"]
auto_write = false

# Other providers, uncomment and edit the one you want. Each needs an app
# specific password, stored later by a helper script, never written here.
# [[account]]
# id = "icloud"
# provider = "imap"
# address = "you@icloud.com"
# imap_host = "imap.mail.me.com"
# imap_port = 993
# smtp_host = "smtp.mail.me.com"
# smtp_port = 587
# auto_send = false
#
# [[account]]
# id = "yahoo"
# provider = "imap"
# address = "you@yahoo.com"
# imap_host = "imap.mail.yahoo.com"
# imap_port = 993
# smtp_host = "smtp.mail.yahoo.com"
# smtp_port = 587
# auto_send = false
#
# [[account]]
# id = "fastmail"
# provider = "imap"
# address = "you@fastmail.com"
# imap_host = "imap.fastmail.com"
# imap_port = 993
# smtp_host = "smtp.fastmail.com"
# smtp_port = 587
# auto_send = false
#
# [[account]]
# id = "outlook-personal"
# provider = "imap"
# address = "you@outlook.com"
# imap_host = "outlook.office365.com"
# imap_port = 993
# smtp_host = "smtp-mail.outlook.com"
# smtp_port = 587
# auto_send = false

No password, token or app password goes into either file, and none goes into
this chat.

STEP 5, verify and summarise.
Run "claude plugin list" one last time and show me the output. Then tell me, in a
short list: which six plugins are installed and at which versions, that
automatic updates are on, and which config files you created or left untouched.

STEP 6, hand back to me.
Tell me to quit Claude Code and relaunch it from a NEWLY OPENED terminal window,
not from the one this session is running in. Two reasons, and say both: the
mcp-mail tools do not appear until the session restarts, and if uv was installed
during STEP 0 then only a new terminal has it on the path. Relaunching from the
same window would start the mail server with no uv, and the tools would silently
never appear. Then tell me that after restarting I should say "set
up the numaco plugins", which runs the guided numaco-setup skill for the parts
nobody can do on my behalf:
  signing in to my own Microsoft 365 account (the first mail call opens a browser
  and the token is cached in my own credential store),
  storing a Google OAuth client and any app specific passwords, only if I want
  Gmail or IMAP accounts,
  generating MY OWN Clockify API key at app.clockify.me under Profile settings,
  then API, and pasting it into the hosted Connect Clockify page. Say explicitly
  that nobody else's Clockify key is included on purpose: a Clockify key
  authenticates as the person who owns it, so using someone else's would file my
  hours under their name.
```
