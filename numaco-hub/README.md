# numaco-hub

The front door for the Numaco Claude plugin packet. It carries no engine of its
own: it is where a new user starts, and where anyone goes to update. It ships
three things, a guided setup skill, an update command, and a skill that opens
folders in Obsidian without hanging the app.

## What it gives you

- **Guided setup** (the `numaco-setup` skill). Opens with the privacy and
  own-accounts promise (you configure your own accounts, each plugin runs locally
  or against your own credentials, no one else can see your data, secrets live in
  your OS credential store), confirms that automatic updates are enabled, then
  routes you through per-plugin setup for whatever you installed (mcp-mail,
  review-kit, numaco-design, dev-process-kit, clockify-mcp). For numaco-design
  nothing needs to be preinstalled: the setup runs the renderer doctor, which
  installs the render dependencies and finds or downloads a browser by itself
  (only a missing Node.js is installed via your package manager), and then
  creates your personal defaults file (copy `defaults.toml.example` from the
  numaco-design plugin root to `~/.config/numaco-design/defaults.toml`); the SOW
  skill asks and offers to write it if it is missing. For dev-process-kit there
  is nothing to configure at all: it stays inert until you run `/contract-init`
  inside a project. It ends by pointing at each plugin's own README and INSTALL
  for the depth.
- **A one-paste onboarding prompt** (`onboarding-paste-prompt.md`). One block you
  can put in an email: the recipient pastes it into Claude Code and it installs
  the packet, merges the auto-update setting into their settings without dropping
  the marketplace source, writes both local config files, and verifies the result
  with `claude plugin list` before handing off to the setup skill. Fill in its
  `<PLACEHOLDER>` values first; they are per recipient and are deliberately not
  stored in this repository.
- **Safe Obsidian vault opening** (the `open-in-obsidian` skill). A vault is the
  whole folder tree beneath its root, and Obsidian stats every file in it on
  every open, so pointing one at a repo root hangs the app on "Loading vault..."
  for minutes or forever. No setting shrinks a vault: the Excluded files setting
  gates only search and graph, never the walk. The skill counts the files that
  are actually in scope (dot directories are skipped by Obsidian, so they must be
  skipped by the count too), holds a measured budget of 10,000 files for a three
  second open, and picks the markdown-dense subfolder when a root is over it. It
  also covers rescuing a vault that is already stuck, including the 0 byte
  `core-plugins.json` that an endless load leaves behind.
- **Updates** (the `/numaco-update` command). Updates are automatic at session
  start when auto update is on for the `numaco` marketplace; this command runs an
  on-demand update (`/plugin marketplace update numaco` then `/reload-plugins`)
  and shows how to check installed versions.

## Start here

Run the setup skill by saying "set up the numaco plugins", "onboard me",
"configure numaco plugins", or "numaco setup". It lives at
`skills/numaco-setup/SKILL.md`.

To update on demand, run `/numaco-update` (see `commands/numaco-update.md`).

## Layout

```
numaco-hub/
├── .claude-plugin/
│   └── plugin.json          plugin manifest (name, version, author)
├── skills/
│   ├── numaco-setup/
│   │   └── SKILL.md         guided onboarding front door
│   └── open-in-obsidian/
│       └── SKILL.md         count a folder before opening it as a vault
├── commands/
│   └── numaco-update.md     the /numaco-update slash command
├── onboarding-paste-prompt.md  the one-paste colleague onboarding block
└── README.md                this file
```

## Where to go next

The hub is deliberately thin. For anything beyond first setup, read the target
plugin's own documentation: mcp-mail's `README.md` and `INSTALL.md`,
review-kit's `README.md`, numaco-design's `README.md`, dev-process-kit's
`README.md`, and clockify-mcp's `README.md`.
