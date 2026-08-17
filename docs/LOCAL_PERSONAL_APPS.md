# Local Mail and Calendar control

Misha uses the Mail and Calendar accounts already configured in macOS. Google Cloud,
Microsoft Entra, OAuth client secrets, paid AI APIs, and account passwords are not
required for this path.

## Supported actions

- `mail_inbox`, `mail_search`: bounded local reads (1–100 results).
- `mail_draft`: creates and opens a draft after exact action approval.
- `mail_reply_draft`: creates a reply in the original thread using the exact numeric
  local Mail message ID; the recipient is derived by Mail rather than retyped.
- `mail_send`: sends only after exact recipient/content action approval. Sensitive
  content requires an additional explicit approval. A local Mail message identifier
  proves submission to Mail, not remote delivery.
- `calendar_list`, `calendar_events`: bounded local reads.
- `calendar_create`, `calendar_update`, `calendar_delete`: exact calendar/event
  mutations after action approval. Update and delete require the exact event ID.

## Security boundary

- User-controlled values are passed as `osascript` arguments; they are never inserted
  into script source or executed by a shell.
- Attachments are limited to regular, non-symlink files under Desktop, Documents, or
  Downloads; executable/script extensions, more than ten files, and totals above
  20 MiB are blocked.
- Reads return bounded, normalized text. Mail previews are capped at 500 characters.
- Mutations use the central single-use approval manager and are never retried
  automatically when the external result is uncertain.
- macOS may request Automation permission for Misha to control Mail or Calendar. This
  permission can be revoked in System Settings > Privacy & Security > Automation.

## Optional cloud adapters

The provider-neutral OAuth contracts remain isolated in the source tree for a future
explicit opt-in. They are not required or selected by the local desktop workflow.
