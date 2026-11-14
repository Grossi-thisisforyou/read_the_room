# Visuals

The picture for INFINITE JEST: one projector, one visitor at a time. It is painted
live on the Raspberry Pi 5 from the camera image, the phone's tilt and the visitor's
profile. Nothing is filmed or kept: the picture is a painting made from the visitor
while they are in the room, and it is painted over when they leave.

## What you see

Every frame is built up in layers, like a painting:

1. **Ground.** A hand-painted room. A flat, saturated field with a floor band, or a
   painted-over wall, a deep dark field, or a column of light. Broad strokes show in the
   paint. The colour drifts slowly across the field (one side warmer, one cooler). The
   light falls off toward the edges into a darker, *more* saturated colour, never into
   black, so it still reads on a wall in a bright room. A painted shadow pool sits under
   the figure. Some scenes have props: a dais, a plinth, a bench or a rug.
2. **Figure.** The visitor, cut out from the room and painted as raw flesh: bruise
   shadows, raw reds and bone lights, mixed differently in different parts of the body.
   The shapes are simplified into flat painted planes and dragged along a flowing field,
   as if wiped with a rag. A faint ghost trails behind every movement.
3. **Brushwork.** Real strokes painted on top of the figure with the visitor's own
   colours. There are five kinds of brush:
   - *wipe*: a wide flat brush that drags paint across and smears what it passes over
   - *scumble*: a dry brush that leaves broken, scratchy paint on the tooth of the canvas
   - *loaded*: thick paint with a lit edge, like impasto
   - *knife*: flat scraped bands
   - *nervous*: thin, shaky lines
   The strokes follow the outline and the flow of the body and stop at its edge. Now and
   then a big arc swipes across the face.
4. **Cage.** A thin painted frame around the figure (a box, an arch, a ring, a rail or a
   picture frame, depending on the scene).
5. **Words and marks.** Hand-drawn words, record numbers, crossings-out, redaction bars,
   barcodes, tally marks, graphs and face boxes. They are drawn at full resolution so they
   stay sharp, and every letter wobbles differently.
6. **Finish.** Canvas texture and grain, a scan line while the visitor is being profiled,
   flicker and slice glitches for nervous profiles.

## Scenes: several per hook

Each hook has four or five different scenes. A visitor gets one chosen for them (so two
visitors in a row rarely see the same picture), and during a long hook phase the scene
changes every so often with a slow fade, a painted wipe or a drag across. A phone shake
cuts straight to the next one.

| Hook | Scenes |
|---|---|
| `flesh` | the figure on a dais in a cage; lying on a bench; a triptych of three panels; the head alone on a plinth; crouched in a corner |
| `scrawl` | a surveillance wall: the figure behind a face box with live graphs and records; a case file; a timeline of time stamps; a redacted page |
| `inverted` | the whole body upside down; an upside-down bust, huge; a double; a fall |
| `mirror` | the visitor's double, mirrored, in a column of light; the eyes only; the mouth only; the face, huge, with an echo |
| `void` | near dark: one line of text; a figure far away; a horizon; a slow breath of light |

An unknown hook name falls back to one of the others, so the wall is never blank.

## How the visitor changes it (OCEAN)

| Trait | High | Low |
|---|---|---|
| Openness | stranger colours, more smear | familiar grounds |
| Conscientiousness | steady cage, words on a grid, clean letters | shaky cage, scattered, wobbly words |
| Extraversion | brighter, bigger figure, bigger words, more marks | darker, smaller |
| Agreeableness | tender words, warm flesh | cold words, grey flesh |
| Neuroticism | twisted face, raw red, flicker, glitches, crossed-out words | calm |

## The phases of a visit

- **idle**: the empty room, an empty cage.
- **approach**: the figure smears in.
- **profiling**: a scan line, the face box, the scores written up as data.
- **hook**: everything above, getting denser the longer they stay.
- **the hinge** (`state.hinge`, about 4 s): the room goes almost black and shows only
  one line, then comes back.
- **release**: the visitor's file (`state.reveal`) is typed out line by line on a
  hand-ruled card with a count like 7/12, and it takes over the picture while the figure
  fades behind it.
- **wipe**: the lines are struck out from the bottom, the deletion lines appear
  (DELETED, NOTHING KEPT), then broad house-painter strokes paint over the whole room.
  Everything held about the visitor is dropped at the start of the wipe.

`state.big_line` puts one large hand-lettered line on the wall, sharp at 1080p.
All of these are optional: if the show engine sends none of them, the picture still works.

## Phone tilt

| Phone | Picture |
|---|---|
| tilt left/right | the figure slides and leans, the smear swings, the cage turns, words slant |
| tilt forward/back | zoom in and out |
| upside down (`steer.flip`) | the whole picture turns slowly upside down |
| shake | a glitch burst, and a cut to another scene |

Tilt reaches the picture in well under 100 ms, in every hook. It is smoothed so a steady
hand gives a steady picture, but big moves come through at once. The module reads
`state.steer {x, y, flip, shake}`, or `state.tilt {x, y}`, or raw degrees from an
`on_sensor()` call. If the show engine is sending `state.steer`, that always wins; raw
tilt is only used when no steer has arrived for a second.

## Where the words come from

In order of priority:

1. words from the local language model (`state.words`)
2. the wall-text corpus written for the piece (`infinite_jest/text/corpus/lines.json`),
   if it is there: short lines for the current hook and phase, tender or cold depending
   on the visitor
3. a built-in vocabulary, so the wall is never empty

The piece's internal names (hook and palette names) are never written on the wall.
Accented letters are drawn without their accents, and long words shrink to fit.

## Image library (optional)

The overnight image generator (`bank_gen/`, see its README) fills `bank/<hook>/`. The
visuals use it in two ways:

- the flat 16:9, poster or grey versions are laid faintly under the ground (square
  originals are cropped to fill, never stretched), preferring pictures painted in the
  current colours;
- the cut-out figures are collaged into some scenes (the triptych, the double) and stand
  in for the visitor when the camera is missing.

Only a limited number of pictures per hook are loaded (the newest half plus a random
sample of the rest), so memory stays bounded. A broken or missing picture is skipped.
The folder is not in git.

## Try it on a laptop

You need Python 3 with numpy and pygame (`pip3 install numpy pygame`). From the
`read_the_room` folder:

```
python3 -m infinite_jest.visuals.demo                  # a window with fake visitors
python3 -m infinite_jest.visuals.demo --image me.jpg   # use a photo as the camera
python3 -m infinite_jest.visuals.demo --webcam         # laptop camera (pip3 install opencv-python)
python3 -m infinite_jest.visuals.demo --stills out/    # JPEG stills of every scene, plus a contact sheet
python3 -m infinite_jest.visuals.demo --capture tour.mp4 --seconds 70 --with-audio   # video with the techno in sync
```

In the window, the mouse stands in for the phone's tilt. Keys: 1 to 5 pick the hook, P
next phase, W wipe, O C E A N raise a trait (with Shift to lower it), V new visitor,
S shake, U upside down, F fullscreen.

## For the show engine

```python
from infinite_jest import visuals
vis = visuals.create((1920, 1080), config)   # config keys below, all optional
vis.on_state(state)        # the contract "state" data, 10 Hz is plenty
vis.on_frame(frame)        # numpy [h, w] gray8 or [h, w, 3] RGB from the camera
vis.on_sensor(data)        # optional raw phone sensor dict
vis.on_text(words)         # optional extra words
vis.on_wipe()              # forget the visitor
vis.render(surface, dt)    # every frame
```

Config keys:

| Key | Default | What it does |
|---|---|---|
| `internal_size` | `(640, 360)` | the painting resolution; scaled up smoothly (words are always drawn at full size) |
| `smooth_scale` | `True` | smooth upscale; False is faster and blockier |
| `frame_budget_ms` | `28` | the quality governor's budget (see Speed); 0 turns it off |
| `upscale_full` | `False` | True: one full smoothscale to the output size instead of half size then 2x (about 1.5 ms slower, a hair softer) |
| `stroke_cap` | `4` | most new brush strokes per frame; the rest carry over to the next frames |
| `figure_w`, `figure_h` | `160`, `180` | size of the figure buffer |
| `bank_dir` | `visuals/bank` | the image library |
| `bank_max_per_hook` | `40` | how many library pictures to load per hook |
| `bank_reload_s` | `600` | at a wipe, re-read the library if it is older than this; done on a background thread, only new files are read, and the new set takes over at the next scene |
| `hook_hold_s` | `6` | a new hook from the profiler takes over only after it has been asked for this long without a break ... |
| `min_scene_s` | `20` | ... and the current scene has been up this long (a phase change, a new visitor, a shake or a phone flip cut at once) |
| `hook_fade_s` | `2.5` | crossfade length from one hook's scene into another's |
| `busy_file` | `/tmp/infinite_jest_busy` | tells the overnight generator a visitor is in; `None` turns it off |
| `corpus_path` | none | a `lines.json` file, or a folder holding one, to use as the wall text |
| `force_variant` | none | always use scene number N of the current hook (for testing) |

Bad or missing state values never stop the picture: anything odd is ignored. If a
frame ever fails, the module draws the last good frame and carries on (set the
environment variable `IJ_VISUALS_STRICT=1` to see the error instead).

## Speed

Measured on the cloud machine it was built on (x86 Xeon 2.3 GHz, one core, 1920x1080
output, default settings) with the realistic show harness
`python3 -m infinite_jest.visuals.profile_show --quick`: idle, three visitors through
every phase with camera frames at 4 fps, a 200-picture bank, reveals, shakes, an
opt-out. About 6.5 ms per frame median, 11 ms at the 95th percentile, 14 to 16 ms at
the 99th (it was 13 / 22 / 26 ms before the speed pass). The slowest phases are the hook
and the release. The final upscale (smooth to half size, then 2x) costs about 1.8 ms.
`--cprofile` and `--tracemalloc` show where the time and memory go, `--level N` pins
a quality level, and `--slow X` makes every frame X times slower to try the governor.

**The quality governor** keeps the frame time under `frame_budget_ms` (default 28 ms,
about 30 fps with headroom on a Pi 5 that also runs the language model). When the
median render time over the last ~3 s is over budget, it steps down one notch:
1 fewer brush strokes and 3 smear taps, 2 `smooth_scale` off, 3 internal picture
480x270. When the median stays under 65% of the budget for 30 s, it steps back up.
There are never two changes within 10 s, and a step up that has to be undone within a
minute doubles the wait before the next try (up to 10 min), so it cannot see-saw. Each
change is printed to stderr (`visuals: t=..s median .. ms over budget ..: quality 0 -> 1
...`). On this machine, the levels measure (median / 99th percentile): 0 6.5 / 15,
1 6.2 / 15, 2 5.9 / 14, 3 4.5 / 11.5 ms. On a Pi 5 the hook frames measured 30 to 45 ms
at full quality before the speed pass, so expect the governor to settle at 2 or 3
there. `python3 -m infinite_jest.visuals.bench` (governor off) measures the fixed
settings and prints the config to use.

## Privacy

Frames live only in memory: the room model, the last frame and a blurred trail at the
figure size, plus a few seconds of echoes. Nothing is written to disk. `on_wipe()` (and
the start of the wipe phase) drops all of it at once, including the painted body.

## What runs live and what is made ahead of time

- **Live on the Pi, every frame:** everything above. The brushes, flesh colour, scenes,
  cage, words and glitches are numpy and pygame code, with no GPU needed.
- **Made ahead of time:** the AI-generated library pictures, made overnight while the
  room is empty.
- **Live but slow:** the local language model writes the words a few seconds behind.

The files: `engine.py` (the layers and timing), `brush.py` (the brushes), `figure.py`
(finding and painting the visitor), `ground.py` (the painted rooms and props),
`scenes.py` (the scenes for each hook), `scrawl.py` (the hand lettering and marks),
`corpus.py` (the wall text), `bankimg.py` (the image library), `palettes.py` (colours).

Projection advice (surface, throw distance, lumens, daylight) is in [PROJECTION.md](PROJECTION.md).
