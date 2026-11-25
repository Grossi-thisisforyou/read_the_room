# Vetter: the guest file is made in the room and stays in the room

A small program for the installation's own computer. It takes the full name of a
guest who booked, searches the public web, and writes a guest file to the Pi's
disk. No cloud service reads the file, no AI company's server sees it, and it is
deleted after the show.

It replaces profiling by a cloud assistant. That was the advice from the course:
the piece can only promise "your profile never leaves this room" if the tool that
builds the profile lives in the room.

```bash
# build a file (refuses without a booking date and a full name)
python3 -m infinite_jest.vetter "Full Name" --booked 2026-12-01 --hint "New School" --hint designer \
        --url https://their-own-site.example

python3 -m infinite_jest.vetter "Full Name" --show      # the guest asks what is held: print it for them
python3 -m infinite_jest.vetter "Full Name" --delete    # the guest asks for deletion: gone now
python3 -m infinite_jest.vetter --purge                 # delete every file past its date (run daily)

python3 -m unittest discover -s infinite_jest/vetter/tests -t .
```

Python 3.9+ standard library only. Files land in `~/.local/share/infinite-jest/guests/<name>/`
as `guest.json` (for the show) and `guest.md` (readable, for the guest), readable by the Pi's
user only.

## What leaves the room, exactly

| Leaves | Stays |
|---|---|
| Search queries: the name plus the hints the guest gave (school, city, job) | The file, every sentence in it, the scores |
| Plain requests for public pages | What the guest says in the room |
| | Everything the local language model reads (it must run on 127.0.0.1; any other address is refused) |

So the honest sentence for the wall and the terms is: **"Your profile is built and kept on the
computer in this room. To build it, the computer searches the web for your name."**
Do not say "nothing leaves the room": a search engine sees the name.

The Pi needs internet while it vets, and none while the show runs. Vet in advance, then unplug.

## What it will not do

- Research anyone without a booking date (`--booked`), or from a first name alone.
- Use a page that names the person but matches nothing they told us. A namesake is left out
  and listed in the file as "might be someone else".
- Log in anywhere, send cookies, or fill forms. It ignores sites behind logins
  (Instagram, Facebook, LinkedIn, X, TikTok) and people-search and data-broker sites.
- Fetch a page that the site's robots.txt closes to it. It identifies itself honestly and
  does not pretend to be a person's browser. Some sites will block it. That is a limit we accept.
- Keep any sentence that touches health, sexuality, religion, politics, immigration status,
  money or family. Those are counted and dropped; only the count is stored.

## How it reads a person

Method v2 (`rules.py`), tested once on a consenting subject (see `research/method-v2.md` in the
project files): start from what is typical for the person's group, weigh a sentence by who is
speaking and how old it is, ignore roles, headlines and house style, count what people do over
how texts sound, and move a trait only when three independent cues agree. One website can vote
at most twice per trait.

Most guests will have little online. Then the scores stay at the starting point, the file says
`"thin": true`, and the room gets to know the guest by talking, exactly as it does with a
stranger. The file's main value is the personal material: quotes and dated facts with sources.

`--no-model` uses word lists only. Without it the tool asks the Pi's own model
(llama-server on 127.0.0.1:8080) to label each sentence and falls back to the word lists if
the model is off or unclear.

## GDPR principles, one line each

- **Lawful basis and transparency:** consent at booking, stated on the booking page; the wall
  and terms say what the computer does.
- **Purpose limitation:** the file shapes one visit. Nothing else.
- **Data minimisation:** public pages only, excluded topics dropped, 12 pages at most.
- **Accuracy:** every line carries its source; namesakes are left out; scores are labelled guesses.
- **Storage limitation:** `delete_after` in every file, `--purge` enforces it.
- **Integrity and confidentiality:** files are private to the Pi's user and never transmitted.
- **Rights:** `--show` gives the guest their file on the spot (show it on screen or print it;
  email it only to the guest and only if they ask), `--delete` erases it.

## Not yet checked

Live web search and fetching could not be run from the build environment (those sites are
closed to it). The parser and pipeline were run against saved pages and a full local copy of a
real site. First live run on the Pi: vet the artist, with `--show` afterwards, and read the log
at the end of `guest.json`.
