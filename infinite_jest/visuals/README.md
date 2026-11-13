# Visuals

The picture for INFINITE JEST: one projector, one visitor at a time, drawn live on the
Raspberry Pi 5 from the N900 camera image, the phone's tilt and the visitor's profile.

## What you see

Every frame is built from six layers:

1. **Ground.** A flat saturated field with a floor band and a dais (Bacon), a patchy white
   wall (Basquiat), or near-black with a slow pulse (void).
2. **Paint.** Raw strokes picked up from the visitor's own colours. The longer someone
   stays, the more of them gets painted.
3. **Figure.** The visitor, cut out from the room, smeared along a flowing field, twisted at
   the face, and coloured as flesh: bruise shadows, raw reds, bone highlights. It is turned
   upside down for the Baselitz hook and mirrored, huge, for the mirror hook.
4. **Cage.** A rotating space-frame box around the figure.
5. **Scrawl.** Hand-drawn words, crowns, © marks, crossings-out, skulls and rib cages. They
   are drawn at full 1920x1080 so they stay sharp, and every letter wobbles differently.
   The words come from the local language model (`state.words`), or from a built-in
   vocabulary of dark data and intimacy when it sends none.
6. **Finish.** A scan line while the visitor is being profiled, flicker and slice glitches
   for nervous profiles, and film grain.

## The five hooks

| Hook | Look |
|---|---|
| `flesh` | Bacon: isolated smeared figure in a cage on a flat orange, violet or red ground |
| `scrawl` | Basquiat: white wall with colour patches, skull and ribs drawn over the body, lots of words |
| `inverted` | Baselitz: upside-down figure, thick raw strokes, sick green ground |
| `mirror` | the visitor's own double, mirrored and life-size in a column of light; words say YOU, STAY, CLOSER |
| `void` | near black, a faint figure, one line of text every 7 seconds |

An unknown hook name falls back to one of the first four, so the wall is never blank.

## How the visitor changes it (OCEAN)

| Trait | High | Low |
|---|---|---|
| Openness | stranger palettes (acid green, violet), more smear, arrows | familiar grounds |
| Conscientiousness | steady cage, words on a grid, clean letters | shaky doubled cage lines, scattered, wobbly words |
| Extraversion | brighter, bigger figure, bigger words, more crowns | darker, smaller |
| Agreeableness | tender words (MADE FOR YOU, STAY), warm flesh | cold words (HARVEST, TARGET), grey flesh |
| Neuroticism | twisted face, raw red, flicker, glitches, crossed-out words | calm |

Intensity drives the stroke rate and how often words appear. The phases move through
it: idle (empty cage, "WAITING"), approach (the figure smears in), profiling (scan line,
the OCEAN scores scrawled as data), hook (everything above), release (words get crossed out,
the figure fades), wipe (broad strokes paint over everything and all visitor data is dropped).

## Phone tilt

| Phone | Picture |
|---|---|
| tilt left/right | the figure slides and leans, the smear swings, the cage turns, words slant |
| tilt forward/back | zoom in and out, the cage pitches |
| upside down (`steer.flip`) | the figure turns upside down (Baselitz) |
| shake | glitch burst and extra smear |

The module reads `state.steer {x, y, flip, shake}` (contract 1.3), or `state.tilt {x, y}`
with `state.tilt_energy`, or raw degrees from an `on_sensor()` call.

## Try it on a laptop

You need Python 3 with numpy and pygame (`pip3 install numpy pygame`). From the
`read_the_room` folder:

```
python3 -m infinite_jest.visuals.demo                  # a window with fake visitors
python3 -m infinite_jest.visuals.demo --image me.jpg   # use a photo as the camera
python3 -m infinite_jest.visuals.demo --webcam         # laptop camera (pip3 install opencv-python)
python3 -m infinite_jest.visuals.demo --stills out/    # save stills of every hook
python3 -m infinite_jest.visuals.demo --capture tour.mp4 --seconds 70 --audio ../audio.wav
```

In the window, the mouse stands in for the phone's tilt. Keys: 1 to 5 pick the hook, P next
phase, W wipe, O C E A N raise a trait (with Shift to lower it), V new visitor, F fullscreen.

## For the show engine

```python
from infinite_jest import visuals
vis = visuals.create((1920, 1080), config)   # config keys below, all optional
vis.on_state(state)        # the contract "state" data, 10 Hz is plenty
vis.on_frame(frame)        # numpy [h, w] gray8 or [h, w, 3] RGB from the N900
vis.on_sensor(data)        # optional raw phone sensor dict
vis.on_text(words)         # optional extra words
vis.on_wipe()              # forget the visitor
vis.render(surface, dt)    # every frame
```

Config: `internal_size` (default `(640, 360)`, the painting resolution, scaled up
smoothly; the words are always drawn at output resolution), `smooth_scale` (default
True), `figure_w` / `figure_h` (default 160x180), `bank_dir` (default `visuals/bank`).

Speed: about 11 ms per frame median at 1920x1080 output on one core of the cloud machine
it was built on (x86). A Pi 5 core is slower, so expect roughly 20 to 30 ms, around 30 fps
at best and comfortably over 15 fps. **Not yet measured on the Pi.** If it is too slow,
set `internal_size` to `(480, 270)` or `smooth_scale` to False.

Privacy: frames live only in memory (the last frame plus a blurred trail at 160x180),
nothing is written to disk, and `on_wipe()` drops all of it.

## Image library (optional)

Pictures in `bank/<hook>/` (PNG or JPG) are laid faintly under that hook's ground. They
are made on the Pi itself by `bank_gen/` overnight (see its README). The folder is not
in git.

## What runs live and what is made ahead of time

- **Live on the Pi, every frame:** everything above. Smearing, flesh colour, strokes,
  cage, words and glitches are procedural numpy and pygame code, with no GPU needed.
- **Made ahead of time:** the AI-generated library images. Stable Diffusion on a Pi 5
  takes minutes per picture, so it can't react within a visit. It runs as a background
  job while the room is empty.
- **Live but slow:** the local language model writes the words a few seconds behind.

Projection advice (surface, throw distance, lumens, daylight) is in [PROJECTION.md](PROJECTION.md).
