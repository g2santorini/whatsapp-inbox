# Sendro Unified Inbox — channel selector cleanup

Staging-only UI fix following the owner's design review.

- Remove the duplicated `All / WhatsApp / Instagram / Refresh` bar above
  the conversation list. Existing Open / Mine / Follow Up remains.
- Use the existing left **CHANNEL** sidebar:
  - **WhatsApp** selects only WhatsApp rows.
  - **Instagram** selects only Instagram rows (read-only for now).
  - **WORKSPACE → Inbox** returns to the default **All**, combining both
    channels in chronological order when both have messages.
- The separate top **Instagram** workspace preview remains available.
- Selecting Instagram triggers a manual reload of Instagram data. No new
  scheduled background polling is introduced.
- The 5-second WhatsApp active-chat poll and 15-second summary/conversation
  polls are not changed. Sending, Quick Replies, assignment and WhatsApp
  backend endpoints are untouched.
- Meta Instagram webhook subscription remains OFF; no account tokens,
  credential settings, database schemas, or production main are modified.

Manual staging checks: hard refresh, confirm no duplicate channel bar,
click the sidebar WhatsApp/Instagram, click Inbox to return to All, open a
WhatsApp chat, verify existing messages/Quick Replies and mobile navigation.
