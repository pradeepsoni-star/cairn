<div align="center">

# Cairn

**An assistant that asks before it does anything.**

Find anything on your computer. Never lose a commitment. Connect your mail and calendar — or don't.

Local-first. Nothing is granted by default. Everything it does is written down.

</div>

---

## The problem

Two things cost every person who works on a computer real hours every week:

**You cannot find your own work.** Windows Search and Spotlight index file *names* and give up on the inside of a PDF, a spreadsheet or a deck. You know the number is in "one of those files from March". You spend eleven minutes looking.

**You forget what you promised.** Not the things on your to-do list — the things you wrote in the middle of a meeting note, or sent in an email on Tuesday. *"I'll send the revised figures on Thursday."* Nobody puts that on a list. Everybody means to.

And one thing stops people installing the tools that would fix it: **they will not hand a program the keys to their documents and their mailbox on the strength of a paragraph in a README.**

Cairn is built around that third problem.

## Consent is the product

Most tools treat permission as a setup step — a checkbox on first run, never seen again, enforced nowhere. Cairn does three things differently, and they are testable claims rather than promises:

**1. Nothing is granted by default.** A fresh install can read nothing, open nothing and send nothing. The first screen asks what you want it to do, then shows you only the permissions those choices actually need.

**2. Reading, writing and sending are three separate decisions.** There is no "allow access to your Gmail". There is *read my email*, *write drafts for me to review*, and *send email as me* — and the third is in its own section, tagged **cannot be undone**, never pre-ticked by any setup preset, and requires you to type the word `allow` to enable it.

**3. What Cairn asks a service for is decided by what you granted in Cairn.** Most products request the widest OAuth scope at sign-in and narrow the behaviour in software — so the token on your machine can do far more than the product admits, and you have to trust it to hold back. Cairn builds the scope list *from your permission choices*. Never granted "send"? No send scope is requested, so the access it holds **physically cannot send**. You can verify that on Google's own permissions page instead of taking this file's word for it.

Every action under a permission appends to a plain-text log you can open in Notepad, and the Permissions screen shows it.

```
2026-09-25 11:48:12   gmail_read     read       42 message(s), query: newer_than:90d
2026-09-25 11:48:12   send_to_ai     sent       6 passage(s) from 3 file(s) to anthropic
2026-09-25 11:51:03   open_files     opened     C:\Users\you\Documents\quote.xlsx
```

## What it does

Each of these is a feature you switch on. A feature that is off has no button **and no working endpoint** — it is absent, not greyed out.

| | |
|---|---|
| **Search inside everything** | PDF, Word, Excel, PowerPoint, RTF, EPUB, Markdown, CSV, code, plain text — and your mail, if you connect it. Full-text, with the matching sentence shown. |
| **Catch what you promised** | Every promise in your documents, notes and email, with its due date read out of the sentence. Split into what *you* owe and what you're *waiting on*. |
| **A daily brief** | What's late, what's due today, what's coming, what changed on disk while you weren't looking. |
| **Quick notes** | Type it, forget it. Searchable immediately, scanned for commitments on the way in. |
| **Email & calendar** | Gmail and Google Calendar, read-only unless you say otherwise. Drafts go to your Drafts folder for you to send. |
| **Ask** | A question answered from your own documents, citing them. Needs an API key *and* an explicit permission. |

## Install

```bash
pip install "cairn-desk[docs]"
cairn
```

`cairn` opens the setup screen in your browser at `http://127.0.0.1:8765`. Python 3.10+, on Windows, macOS and Linux.

| Extra | Adds |
|---|---|
| `[docs]` | Readers for PDF / Word / Excel / PowerPoint. Without it, text, Markdown, CSV and code still work. |
| `[google]` | Gmail, Calendar and Drive. Not installed unless you want it, so a machine that will never connect an account never gets the OAuth libraries at all. |
| `[ai]` | The Ask feature. |
| `[all]` | All of the above. |

### From source

```bash
git clone https://github.com/pradeepsoni-hq/cairn.git
cd cairn
pip install -e ".[docs,ai,google,dev]"
pytest
cairn
```

## The terminal, if you prefer it

```bash
cairn folders --add ~/Documents   # choose what it reads
cairn index                       # read them (incremental after the first run)
cairn search shipping terms       # search inside everything
cairn brief                       # what needs you today
cairn note "Called the bank. I'll send the mandate form on Tuesday."
cairn todo                        # open commitments
cairn todo --done 14              # tick one off
cairn ask "what did we agree on the delivery terms"
cairn stats
```

## How the commitment radar works

Rules, not a model — on purpose. A model asked to "find the commitments" invents them, and a to-do list with four things you never said on it is a list you stop opening after a week. Every item traces back to the exact sentence it came from, and you can click through to the file.

```
"Spoke to the supplier. I'll send the revised figures on Thursday
 and Anita will confirm the container booking by Friday."

  → you owe:      send the revised figures on Thursday      [Thu 5 Mar]
  → waiting on:   Anita will confirm the container booking  [Fri 6 Mar]
```

It deliberately does **not** pick up:

- things already done — *"I have sent the catalogue"*
- questions — *"Should I send the revised quotation?"*
- conditionals — *"If they agree, I'll send the revised terms"*
- promises *not* to act — *"I won't be sending it this week"*
- quoted text from someone else's email inside your own report
- templates with placeholders — *"within [X] business days"*
- markdown headings, table rows, HTML wreckage, spreadsheet rows
- version numbers and decimals that look like dates — `v2.40`, `3.4 million`

Dates are parsed in code rather than by a model, because models are confidently wrong about dates and a to-do with the wrong date is worse than one with no date. `next Friday` said on a Wednesday means the Friday of *next* week. `Friday` said on a Friday means a week today.

Most of that list exists because the tool was run against a real machine with 400 real documents and got each one wrong first.

## Privacy, stated so it can be checked

- Your documents are **read**, never modified, moved or deleted.
- Everything lives in one SQLite file on your machine (`cairn stats` prints where).
- The interface binds to `127.0.0.1` and **refuses to bind anywhere else**. It is not a server.
- Every endpoint that changes or opens something needs a token minted at startup and given only to the page Cairn itself served — so a web page you happen to have open cannot drive it.
- The file-opening endpoint only opens paths already in the index, and cannot run programs.
- **Ask** and **send email** are the only things that reach the internet. Both are off, both are separate permissions, and both are logged.

Delete `%LOCALAPPDATA%\Cairn` (or `~/.local/share/cairn`) and Cairn is gone. Nothing of yours goes with it.

## Connecting Google

Cairn cannot ship a shared OAuth client — that would put every user's mail behind one credential. You create a free one once, in about five minutes, and the Connections screen walks you through it. Then:

1. Grant the Google permissions you want on the **Permissions** screen.
2. Press **Sign in** on **Connections**. Google's consent screen will list *exactly* those permissions and nothing else.
3. Grant something new later, and Cairn tells you the access it holds cannot do it yet, and asks you to sign in again. Escalation costs a deliberate click.

Disconnecting forgets the account but **keeps** what was already read. Removing indexed mail is a separate button, because they are different things to want.

## How it's put together

```
cairn/
  permissions.py   capabilities, grants, refusals, and the activity log
  features.py      what Cairn does, as opt-in units, plus the setup presets
  connectors/      services that are not the local disk
    base.py        the rule: scopes are built from grants, not the reverse
    google.py      Gmail, Calendar, Drive — six permissions, one sign-in
  config.py        where things live, and what you've chosen
  db.py            one SQLite file: FTS5 index + your data, deliberately uncoupled
  extract.py       one reader per format; a reader never raises
  indexer.py       incremental, interruptible, will not prune what it didn't sweep
  search.py        FTS5, with every typed character neutralised first
  dates.py         date parsing in code, not in a model
  commitments.py   the radar
  brief.py         the one screen worth reading first
  ai.py            optional answering
  server.py        localhost, token-guarded, permission-gated
  cli.py           all of the above, from a shell
  web/             one HTML file, one CSS file, one JS file. No build step.
```

Decisions worth knowing before changing it:

1. **Permission is enforced where the action happens**, not where it was configured. Revoke at 11:04 and the 11:05 scan stops, even though indexing was switched on in January.
2. **A damaged permissions file fails closed.** Defaulting to "allowed" after a bad read would be the worst possible bug in this codebase.
3. **The index and your data are uncoupled.** Nothing in `notes` or `commitments` is derived from `chunks`. Reindexing is what people reach for when something looks wrong, so it cannot lose a note or resurrect a ticked-off commitment.
4. **A cancelled sweep never prunes.** Otherwise closing the laptop mid-scan silently empties the index.
5. **Cloud placeholders are skipped.** OneDrive and Dropbox leave zero-byte stubs; opening one triggers a download. An indexer that walks into that pulls gigabytes over someone's connection without asking.

## Tests

```bash
pytest          # runs against a throwaway index, never yours
ruff check .
```

154 tests. The ones in `test_permissions.py` and `test_connectors.py` are written from the position of someone who does not believe this README — they start from a fresh install and try to make Cairn read, open or send something without being told to.

## Contributing

Issues and pull requests welcome. The bar for a new dependency is high — this is a tool people install on a work machine.

## Licence

MIT. See [LICENSE](LICENSE).
