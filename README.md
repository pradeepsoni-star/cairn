<div align="center">

# Cairn

**Find anything on your computer, and never lose a commitment again.**

Local-first. No account, no cloud, no subscription. Your files never leave your machine.

</div>

---

## The two problems this solves

**You cannot find your own work.** Windows Search and Spotlight index file *names* and give up on the inside of a PDF, a spreadsheet or a deck. You know the number is in "one of those files from March". You spend eleven minutes looking for it.

**You forget what you promised.** Not the things on your to-do list — the things you wrote in the middle of a meeting note and scrolled past. *"I'll send the revised figures on Thursday."* Nobody puts that on a list. Everybody means to.

Cairn reads the folders you point it at, indexes every word inside every document, and pulls those sentences back out with their dates worked out.

## What you get

| | |
|---|---|
| **Search inside everything** | PDF, Word, Excel, PowerPoint, RTF, EPUB, Markdown, CSV, code, plain text. Full-text, with the matching sentence shown. Open the file or jump to its folder in one click. |
| **A commitments list you didn't write** | Every promise in your documents and notes, with its due date read out of the sentence. Split into what *you* owe and what you're *waiting on* from other people. |
| **Today** | What's late, what's due today, what's coming this week, what changed on disk while you weren't looking. |
| **Quick notes** | Type it, forget it. It's searchable immediately and scanned for commitments on the way in. |
| **Ask (optional)** | A question answered from your own documents, citing the files it came from. Needs an API key. Everything above does not. |

## Install

```bash
pip install "cairn-desk[docs]"
cairn
```

That's it. `cairn` opens the window in your browser at `http://127.0.0.1:8765`. Point it at a folder, press **Read them now**, and search while it works.

Python 3.10 or newer. Windows, macOS and Linux.

> **`[docs]`** pulls in the readers for PDF/Word/Excel/PowerPoint. Without it Cairn still indexes text, Markdown, CSV and code — it just skips the Office formats rather than failing.

### From source

```bash
git clone https://github.com/pradeepsoni-hq/cairn.git
cd cairn
pip install -e ".[docs,ai,dev]"
pytest
cairn
```

## The terminal, if you prefer it

Everything in the window works from a shell, so Cairn fits inside a script or a scheduled task.

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

It is rules, not a model — on purpose. A model asked to "find the commitments" invents them, and a to-do list containing four things you never said is a list you stop opening after a week. Every item traces back to the exact sentence it came from, and you can click through to the file.

```
"Spoke to the supplier. I'll send the revised figures on Thursday
 and Anita will confirm the container booking by Friday."

  → you owe:        send the revised figures on Thursday     [Thu 5 Mar]
  → waiting on:     Anita will confirm the container booking [Fri 6 Mar]
```

It deliberately does **not** pick up:

- things already done — *"I have sent the catalogue"*
- questions — *"Should I send the revised quotation?"*
- conditionals — *"If they agree, I'll send the revised terms"*
- spreadsheet rows, version numbers, and decimals that look like dates

Dates are parsed in code rather than by a model, because models are confidently wrong about dates and a to-do with the wrong date is worse than one with no date. `next Friday` said on a Wednesday means the Friday of *next* week. `Friday` said on a Friday means a week today. `3.4 million` is not the 3rd of April.

## Privacy, stated so it can be checked

- Your documents are **read**, never modified, never moved, never uploaded.
- Everything lives in one SQLite file on your machine (`cairn stats` prints where).
- The web interface binds to `127.0.0.1` and **refuses to bind anywhere else**. It is not a server.
- Every endpoint that changes or opens something needs a token minted at startup and handed only to the page Cairn itself served — so a web page you happen to have open cannot drive it.
- The file-opening endpoint only opens paths already in the index.
- **Ask** is the single feature that talks to the internet. It is off unless you set a key, and it sends only the passages it retrieved plus your question.

Delete `~/.local/share/cairn` (or `%LOCALAPPDATA%\Cairn`) and Cairn is gone. Nothing of yours goes with it.

## Ask — optional, and genuinely optional

Set whichever you have and restart:

```bash
export ANTHROPIC_API_KEY=...     # or OPENAI_API_KEY, or GEMINI_API_KEY
export OLLAMA_HOST=http://localhost:11434   # fully offline alternative
```

The prompt tells the model to answer **only** from the retrieved passages and to say what is missing rather than guess. Sources are listed under every answer, and you can click through to the file.

## How it's put together

```
cairn/
  config.py       where things live, and what you've chosen
  db.py           one SQLite file: FTS5 index + your data, deliberately uncoupled
  extract.py      one reader per format; a reader never raises
  indexer.py      incremental, interruptible, and it will not prune what it didn't sweep
  search.py       FTS5, with every typed character neutralised before it reaches the query
  dates.py        date parsing in code, not in a model
  commitments.py  the radar
  notes.py        quick capture
  brief.py        the one screen worth reading first
  ai.py           the only file that talks to the internet
  server.py       localhost, token-guarded
  cli.py          all of the above, from a shell
  web/            one HTML file, one CSS file, one JS file. No build step.
```

Three decisions worth knowing if you're going to change it:

1. **The index and your data are uncoupled.** Nothing in `notes` or `commitments` is derived from `chunks`. Rebuilding the index is the thing users reach for when something looks wrong, so it had to be the safest operation available — it cannot lose a note or resurrect a commitment you ticked off.

2. **A cancelled sweep never prunes.** An indexer that deletes everything it didn't reach empties itself the first time someone closes the laptop mid-scan, and does it silently.

3. **Cloud placeholders are skipped.** OneDrive, Dropbox and iCloud leave zero-byte stubs on disk. Opening one triggers a download. An indexer that walks into that pulls gigabytes over someone's connection without asking, and gets uninstalled by lunchtime.

## Tests

```bash
pytest          # the suite runs against a throwaway index, never yours
ruff check .
```

## Contributing

Issues and pull requests welcome. The bar for a new dependency is high — this is a tool people install on a work machine.

## Licence

MIT. See [LICENSE](LICENSE).
