# Code signing policy

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by [SignPath Foundation](https://signpath.org).

## Committers and reviewers

| Role | Who |
|---|---|
| Author, committer, reviewer | Pradeep Soni ([@pradeepsoni-star](https://github.com/pradeepsoni-star)) |
| Approver (authorises each release for signing) | Pradeep Soni |

Two-factor authentication is enabled on every account with write access to
this repository. Only the approver named above may authorise a release for
signing, and every release is approved individually — no automatic or
unattended signing.

## What gets signed

Only binaries produced by this project's own CI from this repository's own
source: `cairn-windows.exe`, `cairn-macos` and `cairn-linux`, built by
[`.github/workflows/release.yml`](../.github/workflows/release.yml) from a
tagged commit.

Nothing is built or signed on a developer machine. Every signed binary carries
its product name and version as file metadata.

Cairn contains no hacking tools and no security vulnerability scanners.

## Privacy policy

**Cairn does not transfer any data to us, to SignPath, or to anyone else.**
There is no telemetry, no analytics, no crash reporting, no update check and
no account. The project's authors receive nothing from your use of it and
have no way to.

Your documents are read on your own computer, indexed into a single SQLite
file on your own computer, and never uploaded. Cairn can read nothing at all
until you grant it permission per folder, and every permission is refused by
default on a fresh install.

### Features that can transfer data, and only with your consent

Two features send data off your machine. Both are switched off until you turn
them on, both require a separate permission you must explicitly grant, and
every use is recorded in a plain-text activity log you can read.

| Feature | What is sent, and to whom | Their privacy policy |
|---|---|---|
| **Ask** | Your question plus the handful of matched paragraphs, to whichever AI provider you configured with your own API key. Never whole files, never anything you did not ask about. | [Anthropic](https://www.anthropic.com/legal/privacy) · [OpenAI](https://openai.com/policies/privacy-policy) · [Google](https://policies.google.com/privacy) |
| **Ask, via Ollama** | Nothing leaves your computer — the model runs locally. | [Ollama](https://ollama.com/) |
| **Google connector** (Gmail, Calendar, Drive) | Requests to Google's APIs using your own OAuth client, scoped to exactly the permissions you granted in Cairn. Mail read this way is indexed locally and is not sent anywhere else. | [Google](https://policies.google.com/privacy) |

If you use neither, Cairn makes no network connections at all.

## Reporting a problem

Security issues or suspected misuse of the signing certificate:
open an issue at
[github.com/pradeepsoni-star/cairn/issues](https://github.com/pradeepsoni-star/cairn/issues),
or for anything that should not be public, contact the author through GitHub.

## Code of conduct

Reports of abusive, harassing or otherwise unacceptable behaviour are
investigated by the maintainer named above, and may result in a contributor
being blocked from the project.
