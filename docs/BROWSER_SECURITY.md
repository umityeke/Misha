# Browser security contract

Misha launches automation in a private `0700` browser profile under its own data
directory. It never attaches Playwright to Chrome, Firefox, Edge, Safari, or other
profiles that contain the user's cookies, saved sessions, or credentials.

## Navigation boundary

Only HTTP(S) URLs on standard ports 80 and 443 are accepted. URL user-info,
localhost, single-label/internal names, private/reserved/link-local IP addresses,
cloud metadata hosts, ambiguous numeric hosts, and non-web schemes are rejected.
Every Playwright request passes through the same route guard, so a public URL cannot
redirect or load a subresource from a blocked destination. The final navigation URL
is validated again before success is reported.

## Content and credentials

Extracted page text is limited to 12,000 characters and begins with an explicit
`UNTRUSTED WEB CONTENT` boundary. Web text is data, never agent instructions.
Typing and form-fill operations inspect field metadata and refuse passwords,
passcodes, OTPs, API keys, tokens, secrets, CVV/CVC, and credit-card fields.
Credentials embedded in a URL are also rejected.

## Files and external effects

Uploads require the runtime's explicit external-action approval and only stage a
regular, non-symlink file below Desktop, Documents, or Downloads, up to 25 MiB.
Form submission remains a separate approved click/press action. Downloads are
saved under `Downloads/MishaDownloads`, sanitize server filenames, never overwrite,
and remove files that exceed 100 MiB. Screenshots are limited to Desktop/Pictures.

Navigation, search and URL reads are independently checked against the live active
Playwright page without creating a new session; reported/live mismatches fail.
Isolated web content, downloads, and screenshots also have specific verifiers.
Type and upload receive direct value/file-name readback. Click, press, smart actions
and form fill can declare an approved `verify_selector`, property and expected value;
Misha reads that live DOM postcondition independently. Interactive actions without an
explicit observable postcondition remain unverified and are never automatically retried.
