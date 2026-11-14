# bank_gen: painting the image library

INFINITE JEST shows faint painted images behind each of its five hooks (flesh,
scrawl, inverted, mirror, void). It takes them from folders:

```
infinite_jest/visuals/bank/flesh/
infinite_jest/visuals/bank/scrawl/
infinite_jest/visuals/bank/inverted/
infinite_jest/visuals/bank/mirror/
infinite_jest/visuals/bank/void/
```

This folder holds the tools that fill those folders and look after them:

- **On the Raspberry Pi, overnight:** a program paints one image at a time
  while nobody is in the room, with no internet. It freezes the moment a
  visitor walks in. Slow (minutes per image) but it never stops growing.
- **On a Mac, in one go:** the same descriptions, painted on the Mac's
  graphics chip, a few seconds per image. Good for filling the library with
  hundreds or thousands of images before the show, then copying them over.
- **Post-processing:** makes 16:9, grey, posterized and cut-out versions of
  every image, ready for the projector.
- **Curating:** a web page that shows the whole library, where you click the
  images you don't want, and a command that removes them (undoably).

Every image gets a small text file next to it (same name, ending `.json`)
with the description it was painted from, the random seed, the model, how long
it took, and **tags** (hook, palette, composition, motifs, theme) so the show
can later pick images by tag.

## What's in here

| File | What it is |
| --- | --- |
| `generate.py` | The Pi's overnight painter. |
| `prompts.py` | The word lists that describe each hook's look. Edit these to change the style. |
| `postprocess.py` | Makes the 16:9 / grey / posterized / cut-out versions. |
| `curate.py` | The review page and the delete / keep / undo commands. |
| `install_sdcpp.sh` | One-time setup on the Pi: the painter program and the model. |
| `infinite-jest-bankgen.service` | Makes the Pi start the painter by itself at every boot. |
| `mac/` | Everything for painting on a Mac (see "Painting on a Mac"). |
| `bankfiles.py`, `pngio.py` | Helpers the other programs share. |
| `tests/` | Checks for the programmer. They use fake images and a fake painter. |

---

## How long things take (estimates)

Nothing here has been timed on a real Pi 5 or a real Mac yet: these are
**estimates** from similar setups. The Mac installer measures your machine
and prints the real number (see below); on the Pi the log shows the seconds
per image.

| Where | One image | In an hour | In a 10-hour night |
| --- | --- | --- | --- |
| Pi 5, 4 steps (default) | 2-5 minutes | 12-30 | 120-300 (fewer if visitors come) |
| Pi 5, `--steps 2` | 1-3 minutes | 20-60 | 200-600 |
| Mac M1 / M2 / M3 (base chip), 2 steps | 1.5-3 seconds | 1,200-2,400 | - |
| Mac Pro / Max chip, 2 steps | 0.6-1.5 seconds | 2,500-6,000 | - |
| Post-processing, with Pillow | under 1 second (0.4 s measured on a desktop PC) | | |
| Post-processing, without Pillow | a few seconds (0.8 s measured on a desktop PC; the Pi is slower) | | |

The first Mac image of a session takes an extra 10-60 seconds while the model
loads, and the very first run downloads it (about 2.5 GB).

---

## On the Pi: painting overnight

### 1. Install once, at home (needs internet)

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

### 2. Make one test image

```
python3 generate.py --count 1 --anytime
```

`--count 1` means make one image and stop. `--anytime` means ignore the
night-time hours. You'll see lines like:

```
2026-11-20 14:02:11  start  hook=void seed=1849302211
2026-11-20 14:02:11  prompt a faint empty chair, almost gone, expressionist oil painting, ...
2026-11-20 14:02:11  sd running, pid 4121
2026-11-20 14:05:02  done   void/20261120-140211_1849302211.png (171 s working)
```

Open the picture it names to check that it worked. If something is wrong, the
program prints a plain error and the last lines from the painter.

To see what it *would* do without painting anything (description, tags and
the exact command):

```
python3 generate.py --dry-run
```

### 3. Leave it running overnight

Easiest: let the Pi start it by itself at every boot.

```
sudo cp infinite-jest-bankgen.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now infinite-jest-bankgen
```

(If your copy of the project isn't at `/home/pi/read_the_room`, change the two
paths inside the `.service` file first.)

Now it waits until 22:00, paints until 08:00, and waits again. Each night has
its own theme (see "Themes of the night"). To check on it:

```
systemctl status infinite-jest-bankgen     # is it running?
journalctl -u infinite-jest-bankgen -f     # watch it work (Ctrl+C to stop watching)
sudo systemctl stop infinite-jest-bankgen  # stop it
```

Or run it by hand in a terminal and leave the terminal open:
`python3 generate.py --theme auto`.

Useful options (add them to the end of the command, or to the `ExecStart` line
of the `.service` file):

| Option | Meaning |
| --- | --- |
| `--hours 23-7` | Paint only between these hours (default `22-8`). |
| `--anytime` | Paint at any hour. |
| `--hook flesh` | Only paint for one hook. |
| `--count 20` | Make 20 images, then stop. |
| `--steps 2` | Fewer steps: faster, rougher (1 to 4; default 4). |
| `--theme auto` | A different theme each night (`mix`: any theme, image by image; `none`: no theme; or a theme's name). |
| `--postprocess` | Also make the 16:9 / grey / posterized / cut-out versions of each new image. |
| `--max-per-hook 400` | Most images to keep per hook (see below). |
| `--threads 3` | CPU cores to use, of the Pi's 4 (default 3). |

### How pausing works

The show creates a small marker file, `/tmp/infinite_jest_busy`, while a
visitor is in the room, and deletes it when they leave. The painter checks
for it before every image and every 2 seconds while painting.

- **Visitor arrives:** the painter is frozen in place (like pressing pause).
  It uses no CPU while frozen; the show gets the whole Pi.
- **Visitor leaves:** the painter carries on from exactly where it was.
- **Paused longer than 10 minutes:** that half-done image is thrown away and
  it waits for the room to be empty to start a fresh one.
  (`--abort-after 600` sets this, in seconds.)

You can test pausing by hand while it paints: `touch /tmp/infinite_jest_busy`
pauses it, `rm /tmp/infinite_jest_busy` resumes it. The log says `paused` and
`resumed`.

If the show writes its state to a file instead, point the painter at it with
`--state-file /path/to/state.json`: it pauses whenever the file's `"phase"` is
anything other than `"idle"`.

Even when it's running, the painter is set to the lowest priority, so the
show always comes first.

### How many images, how much disk (estimates)

- Each image is about **0.3-0.6 MB**. At the default limit of 400 per hook
  (2,000 in all) the bank stays around **1 GB**.
- With `--postprocess`, each image also gets its versions, about **1.5-2.5 MB**
  more (the 16:9 copies are bigger than the square original). Budget about
  4-5 GB for 2,000 images with versions.
- The software and model take about **8 GB** more (source and build under
  1 GB, model 5.2 GB, the 8-bit copy about 1.5-2 GB). After the 8-bit copy
  exists you may delete `~/sd-models/sd_turbo.safetensors` to save 5 GB.
- When a hook reaches 400 images, every new one replaces the **oldest**
  one, so the bank keeps changing without filling the card. Images you
  marked **Keep** (see "Curating") are never replaced.
- If the disk ever gets nearly full (under 1 GB free), it waits instead of
  painting.

---

## Painting on a Mac

For filling the library quickly before the show. You need a Mac with Apple
Silicon (M1, M2, M3, M4; an Intel Mac works but is very slow), about 10 GB of
free disk, and internet for the first run.

**Why this way.** There were two options: build the Pi's painter program
(stable-diffusion.cpp) on the Mac, or use Hugging Face's `diffusers` with
PyTorch's Mac graphics support. We chose `diffusers`, because:

- nothing has to be compiled: everything installs as ready-made packages,
  and the versions are pinned, so every Mac gets the same tested set;
- stable-diffusion.cpp's own build guide currently says its Mac graphics
  (Metal) path is "highly inefficient" for the large calculations these models
  do, so it would mostly run on the CPU;
- the model downloads by itself on the first run, and resumes if interrupted;
- everything lives in one folder (`~/infinite-jest-mac`): delete it and the
  Mac is as before (plus Homebrew and Python, which are harmless to keep).

It uses exactly the same descriptions, folders and `.json` files as the Pi,
so the images can be copied straight across.

### 1. Install once

Get the project onto the Mac (the same folder as on the Pi). Open the
**Terminal** app, type `cd ` (with a space), drag the `mac` folder from
Finder into the Terminal window, press Return, then type:

```
bash install_mac.sh
```

It checks the Mac, installs Homebrew if needed (asks for your Mac password),
installs Python, the painting software (about 1 GB) and the model (about
2.5 GB), then paints three test images and tells you **how many images an
hour your Mac can make**. Expect 10-30 minutes the first time. Run it again
any time: it skips what's done.

### 2. Paint

Double-click **`make_images.command`** in Finder. It asks how many images
to make (and whether to make the processed versions too), then paints.
(The first time, macOS may refuse to open it: right-click it, choose
**Open**, then **Open** again.)

Or in the Terminal, from the `mac` folder:

```
./generate_mac.sh --count 300                 # 300 images, spread over the hooks
./generate_mac.sh --per-hook 200              # top every hook up to 200 images
./generate_mac.sh --count 50 --hook flesh     # only one hook
./generate_mac.sh --count 300 --theme harvest # all in one theme
./generate_mac.sh --count 300 --postprocess   # also make the processed versions
./generate_mac.sh --help                      # every option
```

The images go to **`~/Desktop/infinite_jest_bank`**, in the same five hook
folders. `--steps 1` is fastest; `--steps 4` is richer and about twice as
slow as the default 2. Press **Ctrl+C** once to stop after the current image.

### 3. Copy onto the Pi

With the Pi switched on and on the same network:

```
./copy_to_pi.sh
```

That's this one line, if you'd rather type it yourself:

```
rsync -av --exclude .incoming --exclude .trash ~/Desktop/infinite_jest_bank/ pi@inartwetrust.local:read_the_room/infinite_jest/visuals/bank/
```

It asks for the Pi's password, copies only what's new, and never deletes
anything on the Pi. Restart the show (or reboot the Pi) to load the new
images.

**With a USB stick instead:** copy the five folders (`flesh`, `scrawl`,
`inverted`, `mirror`, `void`) from `~/Desktop/infinite_jest_bank` onto the
stick. On the Pi, open each folder on the stick and copy its contents into
the folder of the same name in `~/read_the_room/infinite_jest/visuals/bank/`.
Copy the `.json` files too; they carry the tags.

---

## Themes of the night

A theme makes one night's batch hang together: it leans the colours, the
surveillance details and the framing one way, and sometimes adds a short
phrase. With `--theme auto` the Pi takes a different theme each night, in
turn, and the night counts from noon to noon, so 22:00 and 03:00 belong to
the same night.

| Theme | Leans towards |
| --- | --- |
| `watched` | camera timestamps, recording dots, crosshairs, night vision; greys and bruise colours; views from above |
| `harvest` | barcodes, price tags, rows of numbers; meat, burnt orange and sodium light |
| `tailored` | tape measures, pins, measuring dots, badges: something made only for you; violet and orange |
| `afterglow` | phone glow, cursors, signal arcs, heartbeat lines; sodium and bruise; close-ups |
| `ledger` | redaction bars, consent boxes, fingerprints; concrete, ash and acid green |
| `tenderness` | heartbeat, a pin over the heart; violet, sodium, meat; close-ups |
| `fever` | heat maps, night vision, scan lines; acid green and meat |

On the Mac the default is `--theme mix` (any theme, image by image) so a
big batch stays varied.

## Changing the look

Edit the word lists in `prompts.py`. Each hook has lists of figures, poses,
kinds of brushwork, settings and painting styles, and each image picks one of
each, plus a palette, a composition and sometimes one or two surveillance
details. The lists are dealt like cards, so nothing repeats until a list has
gone round, and the painter remembers which combinations the bank already
has. That gives tens of thousands of different descriptions per hook.

```
python3 prompts.py                 # print sample descriptions with their tags
python3 prompts.py --theme=fever   # samples in one theme
python3 prompts.py --stats         # how many combinations per hook
```

Keep each line short: the model only reads about the first 75 word-pieces,
and the program drops the least important extras when a description runs
long.

**Compositions** are tagged so the show can use them: position (`left`,
`right`, `centre`), framing (`full-body`, `bust`, `close-up`, `small`,
`high-angle`) and panel (`single`, or `triptych-left` / `-centre` /
`-right` for a panel of a three-part painting). **Palettes** are named after
the show's own colour sets in `visuals/palettes.py` (`triptych`, `papal`,
`acid`, `meat`, `bruise`, `ash`, `sodium`, `concrete`, `rose`, `oxblood`,
`teal`, `lilac`, `putty`, `abyss`, `abyss_red`, `abyss_green`).

---

## Post-processing: versions for the projector

```
python3 postprocess.py
```

For each image in a hook folder it makes, in `bank/<hook>/derived/`:

| Version | What it is |
| --- | --- |
| `NAME.wide.png` | a 16:9 crop, scaled to 1280x720, so nothing gets stretched on the projector. Busts and close-ups are cropped nearer the top, to keep the head. |
| `NAME.mono.png` | the 16:9 crop in greys |
| `NAME.poster.png` | the 16:9 crop reduced to the five colours of its palette, like a screen print |
| `NAME.cutout.png` | the figure cut out of a flat background, with a transparent background, cropped to the figure. Only made when the background is flat enough to cut cleanly; otherwise skipped (the image's `.json` says why). |

Each version has its own `.json` with the original's description and tags
plus `variant:wide` (etc.), and a cut-out's `.json` records where the figure
was. Running it again only does what's new. Options: `--hook flesh`,
`--variants wide,cutout`, `--force` (remake everything), `--prune` (remove
versions whose original was deleted), `--dry-run`.

It runs with or without **Pillow** (a picture library; on the Pi:
`sudo apt install python3-pil`). Without it, it uses slower built-in code and
skips JPEG files. A broken file is reported and skipped, never fatal.

**What the show uses today.** The renderer currently reads only the images
directly in each hook folder, not `derived/`, and stretches each one to the
screen, so square images get squashed sideways. If you want the 16:9 copies
shown now, run:

```
python3 postprocess.py --wide-to-hook
```

That puts each 16:9 copy into the hook folder and moves the square original
into `derived/` (still kept, and still curated with it). The grey, posterized
and cut-out versions wait in `derived/` until the renderer learns to pick by
tag.

---

## Curating: keep what you like

```
python3 curate.py sheet --open
```

This makes a page, `bank/contact_sheet.html`, showing every image in the
bank, and opens it in the web browser. It works offline. On the page:

- click **Delete** on images you don't want, **Keep** on favourites;
- click an image to see it large: **D** = delete and go to the next, **K** =
  keep, arrow keys = next / previous, **Esc** = close;
- filter by hook, or type a tag or words in the box (`palette:papal`,
  `motif:barcode`, `theme:fever`, `chair`);
- your marks are remembered in that browser if you close the page.

When you're done, press **Save list**. The browser saves `curate_list.txt`
in your Downloads folder. Then in the terminal:

```
python3 curate.py apply                 # uses the newest list in Downloads
python3 curate.py apply ~/Downloads/curate_list.txt   # or name it
```

It says what it will do and asks you to type `yes`. Deleted images go into
`bank/.trash/` with their `.json` and all their versions; the show never looks
there. Changed your mind?

```
python3 curate.py restore       # put back what the last apply removed
python3 curate.py empty-trash   # delete the trash for good, when you're sure
```

**Keep** marks a favourite in its `.json`: the Pi's per-hook limit will never
remove it.

**Reviewing on the Mac, deleting on the Pi.** The list names images by their
place in the bank (`flesh/20261120-...png`), so you can make it on one
machine and apply it on another that has the same images: copy the list to the
Pi (`scp ~/Downloads/curate_list.txt pi@inartwetrust.local:`) and run
`python3 curate.py apply ~/curate_list.txt` there.

You can still curate by hand too: delete files in the file manager, move an
image to another hook's folder, or add your own paintings or photos (`.png`
or `.jpg`) to any folder.

The show reads the bank **when it starts**, so changes appear after the
renderer is restarted (rebooting the Pi each morning is enough). It loads up
to `bank_max_per_hook` images per hook (40 by default): the newest half,
plus a random pick from the older ones.

---

## For the programmer

- Command the Pi painter runs (see `--dry-run`): `nice -n 15 ionice -c3
  sd-cli -m MODEL -p PROMPT -n NEGATIVE --steps 4 --cfg-scale 1.0
  --sampling-method euler_a -W 512 -H 512 --seed N -t 3 -o OUT.png`. Extra
  arguments after `--` are passed through, e.g. `-- --vae-tiling`.
- At `--cfg 1.0` (what SD-Turbo is made for) classifier-free guidance is off,
  so the negative prompt has little or no effect. The Mac path uses
  `guidance_scale=0.0` and passes no negative prompt.
- Sidecar fields (both generators): `hook`, `prompt`, `negative_prompt`,
  `parts` (the phrases used), `tags` (`palette`, `composition.{position,
  framing, panel}`, `motifs`, `theme`), `tag_list` (flat `key:value`
  strings), `signature` (id of the combination, used to avoid repeats),
  `prompt_version` (2), `seed`, `model`, `steps`, `seconds`, `created`,
  `generator`; Mac adds `device` and `precision`. `keep: true` is set by
  curate.py. Derived versions add `variant`, `derived_from` and `postprocess`.
- Images older than prompt v2 have no `tags`; postprocess falls back to the
  hook's default palette from `palettes.HOOK_DEFAULT`.
- Half-made images go to `bank/.incoming/` and move into the hook folder only
  when finished; `bank/.incoming/last_sd.log` holds the Pi painter's last output.
- Mac: `mac_generate.py` loads `stabilityai/sd-turbo` through
  `AutoPipelineForText2Image` in float16 on `mps`, with attention slicing. If
  an image comes out all black (half-precision overflow) it reloads in
  float32 and repeats it. `--model sdxl-turbo` or any Hugging Face id also
  works. Packages are pinned in `mac/requirements-mac.txt`
  (`LATEST=1 bash install_mac.sh` installs the newest instead).
- Advanced alternative: stable-diffusion.cpp builds on a Mac with
  `cmake .. -DSD_METAL=ON` and `generate.py` drives it unchanged
  (`--sd-bin`, `--model`, `--anytime`), but see above about its Metal speed.
- `bank/` is git-ignored: images stay on the machine.
- Tests (Linux; about a minute, mostly `test_generate.py`):
  `for t in tests/test_*.py; do python3 $t; done`. `test_postprocess.py`
  runs each image test with and without Pillow when Pillow is installed;
  `test_mac.py` uses a fake painter, so it needs neither torch nor a Mac.
