# bank_gen: the Pi paints its own underpainting

INFINITE JEST shows faint painted images behind each of its five hooks (flesh,
scrawl, inverted, mirror, void). It takes them from folders:

```
infinite_jest/visuals/bank/flesh/
infinite_jest/visuals/bank/scrawl/
infinite_jest/visuals/bank/inverted/
infinite_jest/visuals/bank/mirror/
infinite_jest/visuals/bank/void/
```

This folder holds a small program that **fills those folders by itself, on the
Raspberry Pi, without internet**. It uses an image model (SD-Turbo) running
through a program called stable-diffusion.cpp. Mostly at night, while nobody is
in the room, it paints one image at a time and drops it into the hook that has
the fewest pictures. When a visitor walks in, it freezes at once and lets the
show have the whole computer. When the visitor leaves, it carries on where it
stopped.

Each image gets a small text file next to it (same name, ending `.json`) that
records the description it was painted from, the random seed, the model, and
how long it took.

## What's in here

| File | What it is |
| --- | --- |
| `generate.py` | The generator. You run this. |
| `prompts.py` | The word lists that describe each hook's look. Edit these to change the style. |
| `install_sdcpp.sh` | One-time setup: installs stable-diffusion.cpp and downloads the model. |
| `infinite-jest-bankgen.service` | Makes the Pi start the generator by itself at every boot. |
| `tests/` | Checks for the programmer. They use a fake painter, never the real one. |

## 1. Install once, at home (needs internet)

The venue has no internet, so do this at home. Plug the Pi into your network,
open its terminal and type:

```
cd ~/read_the_room/infinite_jest/visuals/bank_gen
bash install_sdcpp.sh
```

It asks for your password once (to install build tools), then downloads and
builds everything. Expect **about 30-60 minutes** in all, mostly the 5.2 GB
model download and the build. If the internet drops, just run the same command
again: it picks up where it stopped and skips what's already done.

**About the model's licence.** SD-Turbo is made by Stability AI and comes
under the *Stability AI Community License*. It's free for non-commercial and
research use, and for commercial use by anyone earning under US$1M a year who
registers with Stability AI. An art-school exhibition is very likely fine, but
please [read the licence](https://huggingface.co/stabilityai/sd-turbo/blob/main/LICENSE.md)
yourself, especially before you sell anything made with it.

## 2. Make one test image

```
python3 generate.py --count 1 --anytime
```

`--count 1` means make one image and stop. `--anytime` means ignore the
night-time hours. You'll see lines like:

```
2026-11-20 14:02:11  start  hook=void seed=1849302211
2026-11-20 14:02:11  prompt a faint empty chair, thin dark glazes, ...
2026-11-20 14:02:11  sd running, pid 4121
2026-11-20 14:05:02  done   void/20261120-140211_1849302211.png (171 s working)
```

Open the picture it names to check that it worked. One image takes **a few
minutes on the Pi 5** (a rough estimate of 2-5 minutes; we haven't timed it on
the real Pi yet). If something is wrong, the program prints a plain error and
the last lines from the painter.

To see what it *would* do without painting anything:

```
python3 generate.py --dry-run
```

## 3. Leave it running overnight

Easiest: let the Pi start it by itself at every boot.

```
sudo cp infinite-jest-bankgen.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now infinite-jest-bankgen
```

(If your copy of the project isn't at `/home/pi/read_the_room`, change the two
paths inside the `.service` file first.)

Now it waits until 22:00, paints until 08:00, and waits again. To check on it:

```
systemctl status infinite-jest-bankgen     # is it running?
journalctl -u infinite-jest-bankgen -f     # watch it work (Ctrl+C to stop watching)
sudo systemctl stop infinite-jest-bankgen  # stop it
```

Or run it by hand in a terminal and leave the terminal open:
`python3 generate.py`.

Useful options (add them to the end of the command, or to the `ExecStart` line
of the `.service` file):

| Option | Meaning |
| --- | --- |
| `--hours 23-7` | Paint only between these hours (default `22-8`). |
| `--anytime` | Paint at any hour. |
| `--hook flesh` | Only paint for one hook. |
| `--count 20` | Make 20 images, then stop. |
| `--steps 2` | Fewer steps: faster, rougher (1 to 4; default 4). |
| `--max-per-hook 400` | Most images to keep per hook (see below). |
| `--threads 3` | CPU cores to use, of the Pi's 4 (default 3). |

## How many images, how much disk

These are **estimates** until someone times it on the real Pi:

- About **2-5 minutes per image**, so a 10-hour night makes roughly
  **120-300 images**, fewer if people come in during the night.
- Each image is about **0.3-0.6 MB**. At the default limit of 400 per hook
  (2,000 in all) the bank stays around **1 GB**.
- The software and model take about **8 GB** more (source and build under
  1 GB, model 5.2 GB, the 8-bit copy about 1.5-2 GB). After the 8-bit copy
  exists you may delete `~/sd-models/sd_turbo.safetensors` to save 5 GB.
- When a hook reaches 400 images, every new one replaces the **oldest**
  one, so the bank keeps changing without filling the card.
- If the disk ever gets nearly full (under 1 GB free), it waits instead of
  painting.

## How pausing works

The show creates a small marker file, `/tmp/infinite_jest_busy`, while a
visitor is in the room, and deletes it when they leave. The generator checks
for it before every image and every 2 seconds while painting.

- **Visitor arrives:** the painter is frozen in place (like pressing pause).
  It uses no CPU while frozen; the show gets the whole Pi.
- **Visitor leaves:** the painter carries on from exactly where it was.
- **Paused longer than 10 minutes:** that half-done image is thrown away and
  the generator waits for the room to be empty to start a fresh one.
  (`--abort-after 600` sets this, in seconds.)

You can test pausing by hand while it paints: `touch /tmp/infinite_jest_busy`
pauses it, `rm /tmp/infinite_jest_busy` resumes it. The log says `paused` and
`resumed`.

If the show writes its state to a file instead, point the generator at it with
`--state-file /path/to/state.json`: it pauses whenever the file's `"phase"` is
anything other than `"idle"`.

Even when it's running, the generator is set to the lowest priority, so the
show always comes first.

## Curating: keep what you like

The bank is just folders of pictures. **Delete anything you dislike**, in the
file manager or with `rm`; it's fine to delete the `.json` file next to it too.
Move an image to another hook's folder if it belongs there. Add your own
paintings or photos (`.png` or `.jpg`) to any folder. The generator only ever
deletes images when a hook goes over its limit, and then it takes the oldest.
If you want to keep favourites safe from that, copy them somewhere else, or
raise `--max-per-hook`.

The show reads the bank **when it starts**, so new images appear after the
renderer is restarted (rebooting the Pi each morning is enough). It currently
loads only the first 200 images per hook in alphabetical order, and because
the file names start with the date, that means the **oldest** 200. Until the
renderer is changed to prefer newer images, either keep `--max-per-hook 200`
or prune old images by hand so the new ones get shown.

To change the look of a hook, edit the word lists in `prompts.py`: each line
is one possible subject, kind of brushwork, palette or composition, and every
image picks one of each. `python3 prompts.py` prints some sample descriptions.

## Seeding faster from a Mac

A Mac paints much faster than the Pi. You can build stable-diffusion.cpp on the
Mac (see its own instructions) and run the same `generate.py` there, into a
copy of the same folders:

```
python3 generate.py --anytime --count 200 --bank ~/Desktop/bank \
    --sd-bin ~/stable-diffusion.cpp/build/bin/sd-cli --model ~/sd-models/sd_turbo.safetensors
```

Then copy the contents of each `bank/<hook>/` folder onto the Pi's matching
folder (USB stick, or `scp`). The Pi carries on growing the same library.

## For the programmer

- Command the generator runs (see `--dry-run`): `nice -n 15 ionice -c3
  sd-cli -m MODEL -p PROMPT -n NEGATIVE --steps 4 --cfg-scale 1.0
  --sampling-method euler_a -W 512 -H 512 --seed N -t 3 -o OUT.png`. Extra
  arguments after `--` are passed through, e.g. `-- --vae-tiling`.
- At `--cfg 1.0` (what SD-Turbo is made for) classifier-free guidance is off,
  so the negative prompt has little or no effect. It is still passed, and it
  matters if you raise `--cfg` (each step then costs about twice as much).
- Half-made images go to `bank/.incoming/` and move into the hook folder only
  when finished; `bank/.incoming/last_sd.log` holds the painter's last output.
- `bank/` is git-ignored: images stay on the machine.
- Tests (about a minute, Linux): `python3 tests/test_generate.py -v`.
