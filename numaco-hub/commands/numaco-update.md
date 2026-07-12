---
description: Update the Numaco plugins. Updates are automatic at session start when auto update is on; this command runs an on-demand update and shows how to check versions.
---

# /numaco-update — update the Numaco plugins

**Updates are normally automatic.** When auto update is enabled for the `numaco`
marketplace (set `autoUpdate` to `true` under `extraKnownMarketplaces` in your
`settings.json`; the `numaco-setup` skill turns this on), Claude Code pulls new
plugin versions at session start and then prompts you to run `/reload-plugins`.
You usually do not need this command.

## On-demand update (run these two)

To update right now instead of waiting for the next session start:

1. Refresh the marketplace to fetch the latest plugin versions:
   ```
   /plugin marketplace update numaco
   ```
2. Activate them in the running session:
   ```
   /reload-plugins
   ```

## Check installed versions

Open the plugin manager to see each installed plugin and its version:

```
/plugin
```

Each plugin's version also lives in its `.claude-plugin/plugin.json` (the
`version` field), so you can compare what you have against the marketplace.
