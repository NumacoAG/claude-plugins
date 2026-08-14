---
name: open-in-obsidian
description: Open a folder in Obsidian as a vault without hanging the app. Counts the files Obsidian will actually walk and, when the folder is over budget, opens a subfolder instead. Use whenever the user asks to open a folder, repo, project, or notes directory in Obsidian ("open this in Obsidian", "make this a vault", "open my notes", "show this in Obsidian"), whenever a vault is slow or stuck on "Loading vault...", and before registering any new vault root.
---

# open-in-obsidian, pick a folder Obsidian can actually open

Opening the wrong folder as a vault does not fail loudly. It hangs: the window
sits on "Loading vault...", one core stays pegged, and the app is unusable for
minutes or forever. This skill exists so that never happens. Count first, then
open.

## The one fact that governs everything

**A vault is the entire folder tree beneath its root, and Obsidian stats every
file in it on every open.** No setting makes a vault smaller than its folder:

- `userIgnoreFilters` (Settings, Files and links, Excluded files) gates only the
  **metadata cache**: search, graph, backlinks, link suggestions, tags. Excluded
  files are still walked and still become file objects. Verified in the 1.13.x
  binary: `isUserIgnored` is a `MetadataCache` method, and the file walk never
  calls it. Setting it does help search hygiene. It does **not** help load time.
- The only exclusion the walk honours is the hidden rule: any path with a segment
  starting with `.` is skipped, which covers `.git`, `.venv`, `.next`,
  `.pytest_cache` and friends.
- The `ignoreFolders` setting that does exist belongs to **Obsidian Sync**, not
  to the vault.

So the only lever available is which folder you point at. Use it deliberately.

## 1. Count before you open, every time

Count what Obsidian will actually walk, which means excluding dot segments:

```bash
find "<folder>" -type f -not -path '*/.*' | wc -l
```

Never quote a plain `find "<folder>" -type f | wc -l`: it counts `.git`, `.venv`
and every other hidden tree that Obsidian ignores, and it can overstate wildly.
In one real repo tree the raw count was 1,906,605 while only 1,362,973 files were
actually in scope; the other 543,632 were hidden and irrelevant.

On a very large tree the count itself takes a minute. That is already the answer:
if counting is slow, opening will be far slower.

## 2. The budget: 10,000 files

Measured on Apple silicon, local SSD, warm cache, Obsidian 1.13.7:

| files walked | time to open |
|---:|---|
| 25,035 | 4.7s |
| 103,469 | 12.3s |
| 1,362,973 | never finished, still walking after 900s |

`t ≈ 2s + N/10,000` fits the first two almost exactly, then collapses somewhere
past 100,000 files where memory and cache pressure take over. A three second
budget therefore lands on **10,000 files**.

Treat it as a ceiling, not a target:

| count | what to do |
|---:|---|
| under 10,000 | open it |
| 10,000 to 25,000 | open only if the user has a reason, and warn that it takes several seconds |
| 25,000 to 100,000 | do not open, pick a subfolder |
| over 100,000 | refuse, and say plainly that this is minutes, not seconds |

Halve the budget when the folder is on an external drive, a network share, or a
cloud synced location (OneDrive, iCloud Drive). Cloud folders are slower to walk
and `find` under-reports them, because online-only placeholders materialise on
demand.

## 3. Over budget, choose a subfolder

Rank the candidates and take the largest one that fits, preferring markdown
density over raw size:

```bash
for d in "<folder>"/*/; do
  n=$(find "$d" -type f -not -path '*/.*' | wc -l)
  m=$(find "$d" -type f -name '*.md' -not -path '*/.*' | wc -l)
  printf '%9d files %7d md  %s\n' "$n" "$m" "$d"
done | sort -rn
```

In a code repo the answer is nearly always `docs/`. The mass is nearly always
generated: `target/`, `node_modules/`, `dist/`, `build/`, `site-packages/`,
`Library/` and `PackageCache/` in Unity projects, and timestamped report or
artifact directories. None of that is worth indexing.

Report the choice to the user: which folder you picked, its count, and what the
parent's count was. If nothing under the root fits the budget, say so instead of
opening something that will hang.

## 4. Open it

```bash
open "obsidian://open?path=<percent-encoded absolute path>"
```

Percent-encode the path (`/` becomes `%2F`). Observed on 1.13.7: this reliably
raises a vault Obsidian already knows about. Fired at a folder that has never
been registered as a vault it did not open the folder, and in one instance the
app restarted. So for a first-time folder, ask the user to open it once through
the vault switcher ("Open folder as vault"); after that the URI works for good.

## 5. When a vault is already hanging

Symptoms: the window sits on "Loading vault...", and one core is pegged by the
renderer process for that window.

- A single stuck vault window can be closed on its own by killing that window's
  renderer process, which leaves the user's other vault windows untouched. Prefer
  that over force quitting the whole app.
- Expect that vault's `.obsidian/core-plugins.json` to be **0 bytes**. During an
  endless load the debounced config save fires before the plugin config has been
  assigned, and writes an empty file. It is a symptom, not the cause: repairing it
  does not help while the load still hangs, and it is truncated again on the very
  next open. Repair it only once the vault opens normally, by writing a valid JSON
  object; even `{}` is enough, because Obsidian fills in each plugin's default and
  re-saves.
- After closing the window, remove that root from the vault list so it is not
  reopened automatically at the next launch. Obsidian reopens whatever was open
  when it quit, so a hanging vault otherwise hangs every future start.

## 6. What not to do

- Do not add `userIgnoreFilters` expecting a faster open. Worth doing for search
  quality, useless for load time. Saying otherwise wastes the user's afternoon.
- Do not open a repo root that contains build output. Open its `docs/` instead.
- Do not rename, move, or delete directories to hide them from Obsidian. Renaming
  a build directory to a dotted name would work and would also break the build.
- Do not enable Obsidian Sync on a large vault to "tidy" it. Sync has its own
  ignore list, and pointing it at a repo tree is a separate disaster.
