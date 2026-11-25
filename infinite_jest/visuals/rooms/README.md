# Haunted rooms

A second strand of generated pictures for the show: the machine dreams up rooms.
Ordinary interiors, photographic rather than painted, empty in a way that feels
wrong: a chair pulled out, a door ajar onto black, a shape under a sheet, a
silhouette behind frosted glass. They sit beside the colour-field abstractions
and the dark face, and they are graded into the same palettes, so the two strands
read as one body.

Four in ten rooms are fine ones: calm modernist glass, stone and steel interiors
(glass pavilions, onyx walls, reflecting pools, high-tech glass atriums), described
in plain words, never by an architect's name. The haunting is the same.

Rules kept here: no artist is named or quoted, no crowns, skulls or (c) marks,
and no one identifiable is ever in a room (at most a blur, a shadow, a stain).

| file | what it does |
| --- | --- |
| `rooms.py` | the prompt set: 30 worn rooms + 12 fine modernist ones x 17 haunts x 9 lights x 8 cameras x 9 palettes, dealt so nothing repeats soon; tags go into the sidecar |
| `grade.py` | pulls a photograph into one of the show's five-colour palettes, adds grain and a vignette, crops to 16:9 at 1280x720 |
| `make_rooms.py` | makes rooms into `bank/room/` (graded picture + `.json`; the raw model output goes to `derived/`, which the show skips) |

## Making them

Ahead of time on the Mac (the better choice while the Pi runs hot):

    python3 make_rooms.py --painter diffusers --count 60 --bank ~/Desktop/infinite_jest_rooms

then copy `room/` into the Pi's `read_the_room/infinite_jest/visuals/bank/` as a pack.

On the Pi, only when it is cool, slowly and paused while a visitor is present:

    python3 make_rooms.py --painter sdcpp --model ~/sd-models/sd_turbo.safetensors \
        --taesd ~/sd-models/taesd.safetensors --steps 1 --size 384 --threads 2 --rest 600 --forever

## How they enter the show (proposal for the engine)

The show already walks `visuals/bank/` for paintings, so rooms in `bank/room/`
would appear today as ordinary "paint" pieces. To give them their own weight:

- **Collage (TV):** a fifth kind, `room`, chosen when a picture's path has a
  `room` folder: `{"family": 0.40, "photo": 0.22, "paint": 0.18, "room": 0.12, "camera": 0.08}`.
  Rooms keep their colour (they are graded already); no extra look is needed.
- **Wall (projector):** rooms are best large and slow. When the room is empty or
  attention is falling, about a third of the slow ghosts that surface in the
  wall's dream are rooms (14 s fade, like the paintings). While someone is present
  they get rarer, so the visitor meets the face and the abstractions first, and the
  rooms come back as they leave: the machine dreaming where they might have come from.
- **Tags:** `presence: true` rooms can be held back until the visitor has stayed
  a while, and `palette` can follow the mood of the day.

## The living library on the Pi

The Pi cooks the rooms itself, slowly, and the library keeps changing:

- **Grows:** one room at a time, in the gaps, as one turn of the existing painter.
  `paint_turns.py` replaces ij-paint's command inside the same service, so the
  abstractions and the rooms take turns and share one heat budget (its CPUQuota,
  Nice, pause while a visitor is here). No second generator.
- **Forgets:** past `--rooms-max` rooms (120), old rooms begin to fade. Each cycle one
  is chosen at random, older ones more likely, and gets darker, softer and coarser;
  after four fades it is gone. Now and then an old room survives a long time. The
  show just sees the faded file, so forgetting is visible on the wall.
- **Keeps cool:** above 70 C it stops and waits until the Pi is under 60 C, and it
  rests two minutes between pictures.

Proposed ij-paint ExecStart (not installed; the Pi's own thread does that):

    /usr/bin/python3 $HOME/read_the_room/infinite_jest/visuals/rooms/paint_turns.py \
      --model $HOME/sd-models/sd_turbo.safetensors --taesd $HOME/sd-models/taesd.safetensors \
      --rest 120 --room-share 0.35 --rooms-max 120 -- --theme mix --steps 1 --width 384 \
      --height 384 --nice 15 --max-per-hook 80 --abort-after 900
