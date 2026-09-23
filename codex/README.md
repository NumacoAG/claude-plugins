# One source, two hosts

The six root plugin directories remain the canonical workflows, scripts,
templates, and assets. Claude uses `.claude-plugin/marketplace.json` exactly as
before. Do not copy a workflow into a second manually maintained skill.

Codex uses `.agents/plugins/marketplace.json`. Five packages under `plugins/`
are generated from the canonical sources plus the small adapters here.
`mcp-mail` already supports both hosts directly, so its existing source and
version are reused without another copy.

## Maintainer workflow

1. Edit the canonical root plugin for shared behavior. Bump its existing version
   and the Claude marketplace version as required by the publish gate.
2. Edit `codex/adapters/` only for Codex-specific mechanics. Setup/update are
   necessarily host-specific; command workflows are not duplicated here.
3. Stage newly added canonical and adapter files so the builder can include them. It copies
   Git-tracked source files only, never local credentials or build environments.
4. Run `uv run --with pyyaml python scripts/build_codex.py` from the repository.
5. Commit the source and generated changes together. CI refuses stale output.

The build is deterministic across platforms. Each generated plugin's version is
`<shared-version>+codex.<content-hash>`, so a shared or adapter change invalidates
the installed cache without a second manually bumped version. Build output is
committed so colleagues need neither Python nor a build step to install skills.
Python and `uv` are still needed by workflows that execute local scripts/servers.

Native skill frontmatter is normalized at build time. Legacy commands become
native skills pointing to unchanged workflow documents. Claude manifests and
automatic hook registrations are excluded from generated packages to prevent
duplicate commands and accidental cross-host hooks. CLI scripts, templates,
assets, and workflow bodies stay shared. Privacy checks scan generated files too;
only exact previously approved sample tokens are mirrored into their baseline.

## Validation

```text
uv run --with pyyaml python scripts/build_codex.py --check
uv run --with pyyaml python -m unittest discover -s codex/tests
python scripts/publish_gate.py .
```

CI also installs the packet into separate clean Codex and Claude configurations.
The smoke test loads skills through Codex's app-server without a model request or
account sign-in. It expects 26 skills and no command-migration aliases.

## Install in Codex (each machine)

```text
codex plugin marketplace add NumacoAG/claude-plugins
codex plugin add numaco-hub@numaco
```

Start a new task and say **set up the Numaco plugins**. The setup skill installs
the other five and verifies the packet. Unlike Claude, adding only the hub does
not automatically install its dependencies. To install everything from a shell,
run `codex plugin add <name>@numaco` for `numaco-design`, `review-kit`, `mcp-mail`,
`dev-process-kit`, and `clockify-mcp` too.

To update, ask **update the Numaco plugins**. The helper refreshes a clean Git
marketplace and installs changed, missing, or disabled packages. It refuses to
discard local edits and leaves unchanged enabled packages untouched. If an older
hub has no update skill, run `codex plugin marketplace upgrade numaco`, then
`codex plugin add numaco-hub@numaco` and start a new task first.

An existing local-path marketplace must be explicitly switched back to the GitHub
source after preserving local edits. Nothing here silently changes that setting.
There is no claim that another machine has refreshed until it actually does.

## Host differences

- All 26 skill workflows are exposed; Claude session hooks are not registered in
  Codex. Obsidian synchronization must be invoked explicitly there.
- CoreGraphics PDF verification is macOS-specific. On other platforms, use the
  documented independent rendering check and disclose the difference.
- The user's connected accounts, credentials, and preferences remain per machine.
- Account setup, commercial defaults, and external writes still require the
  user's direction. Installing a plugin is not permission to perform them.
