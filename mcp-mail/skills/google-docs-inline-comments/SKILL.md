---
name: google-docs-inline-comments
description: Add a native Google Docs comment to an exact text selection by combining mcp-mail document reads and comment verification with an authenticated browser. Use whenever the user asks to comment on a specific word, sentence, passage, occurrence, or range in a Google Doc, or asks to verify that a comment is visibly attached to selected text.
---

# Google Docs inline comments

Use this workflow only when the comment must appear beside selected text in the
Google Docs editor. The public Drive API cannot create that native editor
anchor. `drive_comment_add` creates a file level comment and must not be used as
a substitute.

This skill coordinates two surfaces:

1. mcp-mail reads the document, validates the target, and verifies the result.
2. The Browser skill operates the authenticated Google Docs interface and
   creates the native comment.

## Required conditions

1. The document must be readable through a Google account configured in
   mcp-mail with the `drive` capability.
2. The Browser plugin must be available. Read and follow
   `browser:control-in-app-browser` before any browser action.
3. Prefer connected Chrome for Google Docs because its authenticated Google
   session persists across agent runs. Use the in app browser only when the user
   explicitly requests it or Chrome is unavailable.
4. A browser session must already be signed in to the Google account that can
   comment on the document. If Google asks for a password, passkey, identity
   verification, or account selection that is not already available, stop and
   ask the user to complete that one time authentication. Never request access
   to the document from another account.
5. The browser must remain connected until verification finishes.

Once these conditions are met, the user does not need to click through the
commenting workflow. This is an agent run, not a persistent background daemon.

## Approval gate

A comment can be visible to colleagues and can notify them. Before opening the
comment composer, show the user one exact staged preview containing:

1. The document title and URL.
2. The exact selected text.
3. The intended occurrence when the text appears more than once.
4. Enough surrounding text to identify the location unambiguously.
5. The complete comment text.

Proceed only after the user explicitly approves that staged version. A general
request to review, comment, or implement the workflow is not approval for a
specific shared document comment.

## Target validation

1. Extract the document ID from the supplied URL. Accept the standard
   `/document/d/<id>/` form.
2. Call `doc_get` with the intended mcp-mail Google account and document ID.
3. Match the requested quote exactly and case sensitively in the returned text.
4. If there is no match, do not approximate. Ask for a corrected quote or use
   additional document context to resolve it.
5. If there is more than one match, require an occurrence number or unique
   surrounding context. Never silently choose the first occurrence.
6. For a multi tab document, or when the flattened text is insufficient, call
   `doc_get_structured` with `include_tabs=true` and resolve the tab as well as
   the occurrence.
7. Call `drive_comments` immediately before the browser write and record the
   existing comment IDs. This snapshot prevents an older matching comment from
   being mistaken for the newly created one.

## Native browser placement

1. Use the Browser skill to claim an existing tab for the exact document when
   one is available. Otherwise, open the exact document URL in the selected
   authenticated browser.
2. Confirm from visible page state that the expected document title loaded, the
   intended Google account is shown, and the document is editable or
   commentable. If the wrong account is active, route through Google's account
   chooser and let the user complete authentication. Never accept or request a
   password, passkey, MFA code, or other credential in chat.
3. If the page says that access is needed, stop. Never click `Request access`.
4. Focus the document editing surface.
5. Open the Google Docs find interface with `Meta+f` on macOS or `Control+f` on
   other platforms.
6. Enter the exact selected text. Read the visible match counter. It must agree
   with the occurrence count already resolved through mcp-mail.
7. Navigate with Enter until the approved occurrence is selected.
8. Press Escape once to close the find interface while preserving the selected
   match.
9. Open the native comment composer with `Meta+Alt+m` on macOS or
   `Control+Alt+m` on other platforms.
10. Confirm that a comment composer became visible. If it did not, stop without
   typing or submitting anything.
11. Enter the approved comment text. Read the composer value back and confirm
    it is exact.
12. Submit through the visible `Comment` control. Do not use coordinate clicks
    when an accessible control is available.
13. Require visible confirmation from Docs that the comment was created and
    that the approved text remains selected. If either signal is missing, treat
    the result as uncertain.
14. Do not retry submission after an uncertain result. A blind retry can create
    duplicate comments.

## Verification

1. Call `drive_comments` again after the interface reports success. Retry the
   read at most three times when propagation is delayed.
2. Find exactly one new comment ID whose content equals the approved comment.
3. Require `anchorText` to equal the approved selected text.
4. For a native Google Docs anchor, require `anchor` to be present and to start
   with `kix.`.
5. Report the new comment ID, selected text, and verified native anchor.
6. If any verification fails, report the mismatch and stop. Do not create a
   second comment automatically.

## Browser cleanup

After verification, release or close browser tabs according to the Browser
skill. Keep the document open only when the user asked to inspect it directly.
