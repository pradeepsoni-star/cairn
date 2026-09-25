# Cairn — user guide

Everything you need, in the order you'll need it.

---

## 1. What it is

Cairn reads the documents already on your computer and does two things with them:

- **Finds them again.** Search what is written *inside* a PDF, spreadsheet, Word file or deck — not just its name.
- **Finds the promises in them.** *"I'll send the revised figures on Thursday."* It pulls sentences like that out and puts a date on them.

It runs entirely on your machine. There is no account and nothing is uploaded. The one feature that uses the internet — **Ask** — is switched off until you turn it on.

---

## 2. Install and first run

Download the file for your system from the [releases page](https://github.com/pradeepsoni-star/cairn/releases/latest) and run it.

**Windows will say the publisher is unknown.** That's because the build isn't signed with a paid certificate — not because anything is wrong with it. Click **More info → Run anyway**. macOS objects the same way: allow it under *System Settings → Privacy & Security*.

Cairn opens in your browser at `http://127.0.0.1:8765`. That address is your own computer; nothing is being served to the internet.

### The welcome screen

1. **Pick what it's for.** Four presets. "Keep everything on this machine" is the cautious one; "Just help me find things" is the smallest.
2. **Tick the features you want.** A feature you leave off has no button *and no working part behind it* — it isn't hidden, it's absent.
3. **Allow only what those features need.** Each permission says what it lets Cairn do **and what it cannot do**. Nothing is granted until you press Start.

Then choose a folder. Pick **one** to begin with — Documents is usually right. Cairn starts reading immediately and you can search while it works.

---

## 3. The screens

| Screen | What it's for |
|---|---|
| **Today** | What's late, due today, coming this week, and what you're waiting on from other people |
| **Search** | Every word inside everything it has read. `"exact phrase"` in quotes, `budg*` for a prefix |
| **Commitments** | The full list, split into what *you* owe and what *others* owe you. Tick to complete, ✕ to say it was never a commitment |
| **Notes** | Type something and forget it. Searchable at once, and scanned for promises on the way in |
| **Folders** | What it reads, and what it has read so far |
| **Permissions** | What it may do, a log of what it *did*, and Start over |
| **Ask** | Questions answered from your documents — see §5 |

**Keyboard:** press `/` anywhere to jump to search.

**Themes:** the button at the bottom-left cycles *system → dark → command → light*. "Command" is a cyan HUD.

---

## 4. Making the commitment list useful

On a real machine, roughly one document in two produces something, and **not all of it is a real promise**. That is expected. The list is only worth having if you prune it.

- **✕ removes it for good.** It won't come back when the file is read again.
- **✓ marks it done.** Also permanent — re-reading the document won't resurrect it.

Spend five minutes pruning on day one. After that it stays quiet.

### What it deliberately ignores

Things already done (*"I have sent the catalogue"*), questions (*"Should I send it?"*), conditionals (*"If they agree, I'll send…"*), promises **not** to act (*"I won't be sending it"*), quoted text from someone else's email inside your report, templates with `[placeholders]`, table rows, headings, and decimals that look like dates (`v2.40`, `3.4 million`).

### How it reads dates

In code, not by guessing. `next Friday` said on a Wednesday means the Friday of **next** week. `Friday` said on a Friday means a week today. `today` means today.

---

## 5. Ask — connecting a model

This is the only feature that sends anything off your machine, and only the
handful of paragraphs it matched plus your question. It needs two things: the
**permission**, and a **model**.

**Step 1.** Allow it: *Permissions → "Send passages to an AI service" → Allow*.

**Step 2.** Go to **Ask**. At the bottom is a **Model** section with a box for
each option. Paste a key, press **Save**, and Cairn immediately tests it and
tells you whether it worked. No environment variables, no restart.

### Which one to pick

| | Cost | Data leaves your machine? |
|---|---|---|
| **Ollama** | Free forever | **No** — runs on your own computer |
| **Gemini** | Free tier, no card | Yes — the matched paragraphs only |
| Anthropic / OpenAI | Paid | Yes — the matched paragraphs only |

### Ollama — free, and nothing leaves your computer

Best fit if privacy is why you're here.

1. Install from [ollama.com](https://ollama.com) — a normal installer.
2. Download a model:

   ```bash
   ollama pull llama3.2
   ```

   **Size matters more than you'd expect.** `llama3.2` is 3B parameters, about
   2 GB, and runs on an ordinary laptop. The 8B models want roughly 6 GB of RAM
   and, without a graphics card, take minutes per answer — which reads as
   broken rather than slow. Start small; you can always pull a bigger one.

3. In Cairn: **Ask → Model → ollama**, leave the address as
   `http://localhost:11434`, press **Save**.

### Gemini — free tier, nothing to install

1. Get a key at [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
   — free, about two minutes, no card.
2. In Cairn: **Ask → Model → gemini**, paste it, press **Save**.

### Where the key is kept

In `model.json` in Cairn's own folder on your computer, readable only by you.
Cairn **never shows a key back to you** — once saved you see only the last four
characters, so you can tell one key from another — and **never writes one to
the activity log**, which is a plain text file you might reasonably send to
someone helping you.

If you already have `ANTHROPIC_API_KEY`, `GEMINI_API_KEY` or `OLLAMA_HOST` set
as environment variables, those still win over anything typed into the app —
so a machine configured by you or your IT department keeps behaving that way.

An operating-system credential store (Windows Credential Manager, macOS
Keychain) would be better than a file, and is the obvious next step. Saying so
is better than implying a JSON file is more than it is.

## 6. Connecting Gmail and Calendar

Built, but it needs a free Google Cloud OAuth client that you create once — about five minutes. Cairn can't ship a shared one, because that would put every user's mail behind a single credential.

The design worth knowing: **Cairn asks Google only for what you granted in Cairn.** Reading, drafting and sending are three separate permissions. If you never allow "send email as me", no send permission is requested, so the access Cairn holds **cannot** send — and you can check that on Google's own permissions page rather than trusting this document.

Sending additionally requires you to confirm the specific message. Two independent gates.

---

## 7. When something goes wrong

### Start over

**Permissions → Start over.** Two options:

- **Run setup again** — choose your settings from scratch, keep everything Cairn has read.
- **Erase everything** — as if freshly installed. You type `erase` to confirm, and **a restorable copy is saved first**; the screen tells you where.

From a terminal:

```bash
cairn reset             # shows what it would do, changes nothing
cairn reset --yes       # run setup again
cairn reset --all --yes # erase everything (backup taken first)
cairn reset --list-backups
```

### Common problems

| Symptom | Cause |
|---|---|
| **No welcome screen** | Setup was already completed in this data folder. *Permissions → Run setup again.* |
| **Search finds nothing** | Check the folder is listed under *Folders*, and that *Read the folders you choose* is allowed. |
| **Nothing happens when I click** | The page may be stale. Reload the tab. |
| **"Address already in use"** | Another copy is already running — look for it at `http://127.0.0.1:8765`. |
| **It stops updating when I close it** | Correct. The background sweep only runs while Cairn is open. |

### Where everything lives

`cairn stats` prints the folder. Typically `%LOCALAPPDATA%\Cairn` on Windows, `~/Library/Application Support/Cairn` on macOS, `~/.local/share/cairn` on Linux.

Delete that folder and Cairn is gone completely. Nothing of yours goes with it.

---

## 8. What it cannot do

Worth knowing before you invest time:

- **WhatsApp.** There's no legitimate way to read a personal WhatsApp account. If your work lives there, Cairn will help less than you want.
- **Phone calls.** Invisible unless you write a note afterwards.
- **Your phone.** It's a desktop tool; the documents it indexes are on your computer.
- **Run when closed.** The sweep only runs while Cairn is open.
- **Judge whether silence means anything.** It shows you what's late. You decide what that means.

---

## 9. The terminal, if you prefer it

```bash
cairn setup --preset find --yes     # choose what it's for
cairn permissions                   # see what it may do
cairn permissions --allow read_folders
cairn folders --add ~/Documents
cairn index                         # read them
cairn search shipping terms
cairn brief                         # what needs you today
cairn note "Called the bank. I'll send the mandate on Tuesday."
cairn todo
cairn todo --done 14
cairn ask "what did we agree on delivery terms"
cairn stats
```
