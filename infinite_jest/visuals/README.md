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

Measured on the cloud machine it was built on (x86, one core, 1920x1080 output):
about 11 ms per frame median, 13 to 16 ms at the 95th percentile. By hook: flesh 11,
scrawl 11, inverted 11, mirror 10, void 8. About 4 ms of that is the final smooth
upscale. On a Pi 5 the hook frames measured 30 to 45 ms at 1080p (22 to 30 fps). The knobs,
in order: first `smooth_scale` False (about 25% less), then also `internal_size`
`(480, 270)`. `python3 -m infinite_jest.visuals.bench` measures both and prints
the config to use.

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
