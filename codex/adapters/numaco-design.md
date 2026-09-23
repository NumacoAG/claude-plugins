# Using Numaco Design in Codex

Keep the skill's content, brand, review, and approval requirements. Adapt only
the host-specific mechanics below.

- Resolve the plugin root from the loaded skill's path. Replace
  `${CLAUDE_PLUGIN_ROOT}` in examples with that absolute directory; use an
  available Python interpreter and the current shell's quoting syntax.
- An instruction to open a Claude live artifact means an editable budget or
  preview. Use Codex's available visualization capability, a local HTML preview,
  or a table in the conversation. Carry the approved values into the document;
  do not require an unavailable Claude artifact API or invent a commit event.
- Open HTML previews with Codex's file/browser preview capability or the
  operating system's registered browser. `open -a` is a macOS example.
- Keep the final PDF authoritative. On macOS, use the specified CoreGraphics
  verification. On Windows or Linux, rasterize the final PDF with an available
  independent renderer such as Poppler or MuPDF and inspect the pages. State
  that this does not verify macOS Preview fidelity. Do not call `sips` or claim
  a CoreGraphics check passed on an unsupported platform.
- Run the existing build and overflow checks; preserve assets and templates.
  If a build script reports a platform limitation, report it accurately rather
  than changing its commercial content or claiming success.
- Codex uses installed plugin copies. After shared source changes, run the
  repository's `scripts/build_codex.py`; it derives a content-based version.
  Reinstall from the configured marketplace and start a new task.
