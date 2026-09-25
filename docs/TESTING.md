# Putting Cairn in front of five people

This is not a launch. It is an experiment with one question:

> **Does anyone who is not Pradeep want this?**

Five people is enough to answer it. If three of them ask when they can have
it properly, there is a product. If they say "interesting", there is not —
and that is a result worth having for a week's effort rather than a year's.

---

## What to send them

Keep it short and unexcited. Overselling ruins the test, because you will get
politeness back instead of information.

> I built a small thing that reads the documents on your computer and finds
> the promises buried in them — "I'll send the figures Thursday", that sort
> of thing. It also searches inside your files rather than just their names.
>
> It runs entirely on your own machine. No account, no cloud, nothing is
> uploaded. It can't read anything until you tell it which folders.
>
> Would you try it for a week and tell me if it's useless? Genuinely fine if
> it is — that's what I'm trying to find out.
>
> Download: <link>
> Windows will warn you it's from an unknown publisher — that's because I
> haven't paid for a code signing certificate yet. Click More info → Run anyway.

## Who to pick

You want people whose work looks like the problem, not people who will be
kind to you.

- Someone who quotes buyers and chases them — the core case.
- Someone drowning in documents but not in email.
- Someone non-technical. If they cannot get past the download, that is the
  most valuable finding of the five.
- Someone who will actually tell you it is rubbish.
- Someone outside your company, so the answer is not politeness.

## Watch, do not help

Sit with at least two of them for the first five minutes and **say nothing**.
Every time you want to explain something, write it down instead — that is a
thing the product should have explained itself.

Note where they hesitate:

- Do they get past the Windows publisher warning, or stop there?
- Do they understand the setup screen, or click the first thing?
- Do they pick a folder, or not know which one?
- When the commitments appear — is the first reaction *"that's useful"* or
  *"where did that come from"*?

## The only questions worth asking, after a week

1. Did you open it again after the first day? (If no, nothing else matters.)
2. Did it find anything you had actually forgotten?
3. What did it get wrong?
4. What would make you pay for it? — **not** "would you pay", which everybody
   answers yes to and nobody means.

## What counts as a yes

Not enthusiasm. Not "this is great". Only these:

- They are still using it in week two without being reminded.
- They ask for something specific — *"can it do my email"*, *"can my
  assistant see this too"*.
- They ask what it costs before you mention money.

## Known rough edges — say these upfront

Being straight about these buys you honest feedback instead of polite
silence.

- **Unsigned build.** Windows and macOS will both complain. Nothing to do
  about it until there is a reason to spend on a certificate.
- **Nothing runs when it is closed.** The index updates while Cairn is open
  and not otherwise.
- **Gmail needs a five-minute Google Cloud setup** that no ordinary tester
  will do. Treat this round as files-only.
- **The commitment list will contain noise.** On a real machine roughly half
  the documents produce something, and not all of it is a real promise. The
  cross button exists for exactly this. How much noise they tolerate before
  giving up is one of the things worth learning.
- **No phone, no WhatsApp.** A lot of Indian B2B lives in WhatsApp and there
  is no legitimate way to read it. If every tester says this is the dealbreaker,
  that is the single most valuable thing this exercise could tell you.
