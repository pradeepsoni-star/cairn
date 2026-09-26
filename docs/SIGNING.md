# Code signing

Every download currently shows **"Windows protected your PC — unknown publisher"**.
That warning is where most non-technical testers stop, and it is not a
reflection on the build: it appears because the executable is not signed.

Worse, while unsigned, SmartScreen reputation attaches to the **file hash**, so
every new release starts from zero. The warning never fades with age.

## The fix, and it is free

[**SignPath Foundation**](https://signpath.org/) signs releases for qualifying
open-source projects at no cost. The certificate's private key stays in their
HSM; signing happens inside the CI pipeline, so no key ever touches this
repository or a developer machine.

Worth knowing before considering the paid route: since 2024, EV certificates
(£300+/year) go through the same reputation-building process as OV ones, so
paying purely to skip SmartScreen no longer buys what it used to.

## Where Cairn stands against their criteria

| Requirement | Cairn |
|---|---|
| OSI-approved licence, no commercial dual-licensing | ✅ AGPL-3.0-or-later |
| No proprietary or closed components | ✅ every dependency is open source |
| Publicly accessible repository | ✅ |
| Releases built from CI | ✅ `.github/workflows/release.yml` builds all three platforms |
| Actively maintained | ✅ |
| Already released in the form to be signed | ✅ releases published for all three platforms |
| Functionality described on the download page | ✅ README and the release notes |
| No malware or unwanted behaviour | ✅ — and the permission model plus the activity log make this checkable rather than assertable |
| 2FA on the GitHub account | ✅ enabled 26 Sep 2026 |

Every criterion is met. What is **not** yet met is the application form's
required "Reputation" field: at the time of writing the project is days old
with no stars, no coverage and a handful of downloads, all of them the
author's own testing. Applying with nothing to point at invites a refusal
that makes a later, stronger application harder, so this waits until there
are real users to describe.

## Applying

1. Turn on two-factor authentication for the GitHub account, if it is not already.
2. Apply at [signpath.org/apply](https://signpath.org/apply).
3. On approval, add the SignPath signing step to `release.yml` between the
   build and the upload.

Their review is done by a person, so allow time. Nothing about the project
needs to change to qualify.

## What to tell testers until then

Say it before they hit it, in the message rather than after the fact:

> Windows will warn you the publisher is unknown — that is because I have not
> paid for a code signing certificate, not because anything is wrong with the
> file. Click **More info → Run anyway**.

macOS behaves the same way; the file is allowed under *System Settings →
Privacy & Security*.

## Verifying a download without a signature

Until signing is in place, the honest alternative is a checksum. After a
release, publishing the SHA-256 of each asset lets a cautious person confirm
that what they downloaded is what was built:

```powershell
Get-FileHash .\cairn-windows.exe -Algorithm SHA256
```

```bash
shasum -a 256 cairn-macos
```

This is weaker than a signature — it proves the file was not altered in
transit, not who made it — but it is better than nothing and costs nothing.
