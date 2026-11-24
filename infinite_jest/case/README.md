# The shell: case and boot look

Two halves of one object: the physical housing for the Raspberry Pi 5, and what
the projector shows while the Pi boots. Both follow the piece's references:
Bacon's cage and smeared flesh, Baselitz's upside-down figures, scrawled
caps and crossed-out words. Deep, dark, industrial.

Concept drawings, materials and the recommended build are on the case page:
https://claude.ai/artifact/K8ieND4PyYRjzZzYYN21oY (private to Baby). This folder holds the files for the Pi.

## Recommended case: the printed cage (print/)

Baby's school can 3D print, so the case is two printed parts. Both print flat
with no supports.

| File | Size | Time (approx.) |
| --- | --- | --- |
| `print/cage_base.stl` | 126 x 82 x 33 mm | 3.5 h |
| `print/cage_lid.stl` | 100 x 72 x 6 mm | 1.5 h |
| `print/cage_case.scad` | OpenSCAD source; every size is a variable at the top | |

Look: the walls are vertical bars (Bacon's curtain streaks), the lid has a
space-frame box in raised ribs, J R A in scrawled caps, and INFINITE JEST lettered
upside down (Baselitz). DARK DATA / CUSTOM MADE INTIMACY / IN ART WE TRUST
are pressed into the underside.

Print settings: **PETG or ASA, matte black** (not PLA, which softens around
55 C next to a warm Pi), 0.2 mm layers, 3 walls, 20 % infill, no supports.
Base floor-down, lid flat with the letters facing up.

Hardware: official Pi 5 Active Cooler and 27 W supply, 4x M2.5 x 6 mm
self-tapping screws (Pi to standoffs), 4x M3 x 12 mm self-tapping screws (lid
to corner posts), 2 screws through the ears into the desk, zip ties through
the floor slots, a steel security cable through the slot at the microSD end.

Ports: USB x4 and Ethernet through the open end, USB-C and both micro-HDMI
through the side window, microSD through a slot under the board. The router
stays outside next to it.

To change a size, edit the variable in `cage_case.scad` and export again:

```bash
openscad -D 'part="base"' -o cage_base.stl cage_case.scad
openscad -D 'part="lid"'  -o cage_lid.stl  cage_case.scad
```

Not yet test-printed: print the lid first (cheap, quick) and check the screw
holes line up before printing the base.

## Alternative printed case: The Smear (print/smear_*)

A head sliced into 16 thin vertical fins. Each fin drifts sideways, bobs and
twists a little more than the last, so the head is a motion blur frozen in
plastic: from the front it resolves into a face, from an angle it smears.
The mouth is open in a scream and the Pi glows inside it. The gaps between
fins are the ventilation.

| File | Size | Notes |
| --- | --- | --- |
| `print/smear_head.stl` | 124 x 147 x 147 mm | Base plate + fins, prints upright, no supports. About 380 cm3, a 12-16 h print. |
| `print/smear_sled.stl` | 112 x 61 x 12 mm | The Pi screws onto it and it slides into the mouth from the back. About 1 h. |
| `print/smear_head.scad` | OpenSCAD source | `smear_amp`, `lift`, `tilt` change how violent the smear is. |

Needs a printer bed of at least 130 x 125 mm and 150 mm of height. PETG or
ASA, matte black, 0.2 mm layers, 20 % infill. Fins are 2.2 mm, so they print
solid. Hardware: 4x M2.5 x 6 mm (Pi to sled), 2x M3 x 10 mm (sled to base).
Ports: USB and Ethernet out the back of the head, USB-C and micro-HDMI
through the open side, microSD through the mouth.

## Third printed case: The Black Box (print/black_box*)

A faceted black stone split along its horizon. The top floats 7 mm above the
bottom on three pillars, so a thin line of the Pi's light runs all the way
round, and a jagged crack across the top glows too.

| File | Size | Notes |
| --- | --- | --- |
| `print/black_box_bowl.stl` | 164 x 146 x 53 mm | Foot down. Pi standoffs, pillars, cable notches. No supports. |
| `print/black_box_dome.stl` | 168 x 147 x 69 mm | Flat cut face down. Solid in the model, prints with sparse infill. No supports. |
| `print/black_box.scad` | OpenSCAD source | Change `seed` for a different stone, `jitter` for rougher facets. |

Bed at least 170 x 150 mm. PETG or ASA, matte black, 15 % infill.
Hardware: 4x M2.5 x 6 mm (Pi), 3x M3 x 16 mm pan head (dome to pillars,
down the three holes in the top). Plug the cables in with the dome off and
lay them in the two notches, then put the dome on.

## Pocket case: Stone (print/stone*), current direction

Since Nov 24 (later the same day): practical, best for the Pi, nice in the hand
and in a bag. A geometric pebble of about 32 facets of very different sizes, rounded
deep (10 mm) where they meet as if washed by the sea, on one flat bottom.
The top is an uneven crown of four low facets, each tilted its own way.
J R A is pressed into each shell's top and raised inside it; the underside
of the tray carries the owner and return text. Three parts:

| File | Size | What it is |
| --- | --- | --- |
| `print/stone_tray.stl` | 122 x 101 x 13 mm | Flat bottom. Holds the Pi on four standoffs, microSD slot, air slots, click rim. |
| `print/stone_work.stl` | 121 x 100 x 40 mm | Shell for working: vent slits over the fan and along the GPIO side, every connector and the power button open. |
| `print/stone_travel.stl` | 125 x 102 x 40 mm | Shell for the bag: closed, protects the ports. |
| `print/stone.scad` | OpenSCAD source | `seed` cuts a different stone, `clr` / `bump_d` tune the click. |

Either shell clicks onto the tray (ridges in the shell snap into a groove in
the tray's rim); pull straight up to open. Tray prints bottom down without
supports; shells print rim down with tree supports from the build plate,
which touch only the inside of the crown. PETG or ASA, 0.12 mm
layers, 4 walls. Spec: `print/stone_PRINT_SPEC.txt`. Not yet test-printed:
print the tray and the travel shell first and try the click.

## The device case: Pavilion (print/pavilion*)

Since Nov 24 Baby wants the Pi treated openly as a device: easy to use,
every port and the power button reachable, good cooling, safe, in a Mies van
der Rohe style. A podium slab on a recessed plinth, a curtain wall of 1.2 mm
mullions (the slots between them are the ventilation), four cruciform corner
columns, and a 4 mm roof slab floating on a 3.5 mm shadow gap so warm air
leaves all the way round.

| Opening | What it serves |
| --- | --- |
| microSD end | power button, status LEDs, microSD card |
| long side | USB-C power, micro-HDMI 0 and 1 |
| short end | 4x USB, Ethernet |
| roof | 4 countersunk M3 x 10 screws; lift it for GPIO and fan |

`pavilion_base.stl` 115 x 82 x 35 mm, `pavilion_roof.stl` 105 x 76 x 4 mm,
no supports. PETG or ASA, 0.12 mm layers for best quality. Port positions
are from the Pi 5 layout and Baby's board photo; print the base once in
draft to check the fit before the final print.

## The device case, second take: Prairie (print/prairie*)

The same functional brief as Pavilion (same three port openings, same
standoffs, roof on four screws), after Frank Lloyd Wright: a long low
plinth, walls of horizontal louvers (the ventilation), an L-shaped terrace
cantilevered on 45 degree undersides, a ribbed stone chimney that doubles as
a flue, and a double roof with a Prairie art-glass pattern cut over the fan.
`prairie_base.stl` 115 x 84 x 51 mm, `prairie_roof.stl` 113 x 84 x 6 mm, no
supports. Print the base in sand, the roof in brick red.

v2 (Nov 24): 2.4 mm walls, corner piers moved outside the walls (v1's
corner posts touched the board corners), heat-set insert holes (set
`threads = "self"` for plain screws), gusseted standoffs, a 45 degree inner
fillet where walls meet the podium, shorter 12 mm louver bridges, 0.5 mm
more clearance on every opening, port labels engraved in the podium, and a
`fitcheck` part that comes out empty when the board clears everything.

## Hidden case: The Wall Box (print/wall_box*), chosen direction

Baby's direction since Nov 23: hide the Pi in plain sight in room 401. This
is a plain white surface-mount electrical box, 170 x 122 x 64 mm. A real,
store-bought 3-gang keystone wall plate screws onto it (standard US screw
spacing), with real HDMI, Cat6 and USB keystone couplers, so the projector,
router and speaker plug into "the wall". The Pi sits inside on standoffs.
Power leaves through a slot in the bottom to the outlet beside it. Air slots
sit on the top and bottom faces, close to the wall.

Print back-down, white PETG, no supports. Sizes follow standard plates and
are not yet checked against the plates in the room.

## Backup case: the junction box

A steel electrical pull box, 12 x 12 x 4 in, painted matte black and scrawled
with oil stick, lettered upside down. The Pi sits inside on standoffs, the
Linksys router is strapped on top with its antennas up (Wi-Fi does not get out
of a steel box, so the router must stay outside). Only low-voltage cables go
in: nothing inside is above 12 V, so it is safe to touch.

If the printers are booked: everything comes from one hardware store trip, it
builds in two evenings without a laser cutter, it locks, and it can be
cabled to the desk so nobody walks off with it.

### Shopping list

| Qty | Item | Notes |
| --- | --- | --- |
| 1 | Steel screw-cover pull box, 12 x 12 x 4 in, with knockouts | Electrical aisle. Grey is fine, it gets painted. |
| 1 | Raspberry Pi 5 Active Cooler (official) | Required. The bare board throttles within minutes under load. |
| 1 | Raspberry Pi 27 W USB-C power supply (official) | Weaker supplies cause random crashes on a Pi 5. |
| 1 | 5 V USB fan, 60 or 80 mm | Exhaust. Plugs into a Pi USB port. |
| 4 | M2.5 x 10 mm brass standoffs, with M2.5 screws and nuts | Pi mounting. Holes are 58 x 49 mm apart. |
| 1 | Scrap 1/4 in plywood or 3 mm acrylic, about 6 x 4 in | Carrier plate for the Pi. |
| 2-3 | 1/2 in NM cable clamp connectors | Strain relief in the knockouts. |
| 1 | Scrap 1/4 in hardware cloth (or aluminium gutter mesh) | Covers the open vent knockouts. |
| 1 | 30 cm micro-HDMI to HDMI cable | Tied down inside so a yank on the projector cable never hits the Pi's port. |
| 2 | 1 in galvanized plumber's strap, about 40 cm each, with nuts and bolts | Straps the router onto the lid. |
| 1 | Vinyl-coated steel security cable, about 6 ft, with a padlock | Through a knockout, around a desk leg. |
| - | Zip ties, adhesive tie-down mounts | Cable management. |
| - | Matte black spray paint, oil sticks (red, flesh pink, bone white), a white paint marker | Finish. Markal Paintstiks are the welders' oil sticks. |

Tools: drill with a step bit, screwdriver, hammer plus flat screwdriver for the
knockouts, tin snips, gloves, safety glasses. The school shop has the drill.

### Build

Evening 1 (about 3 hours)
1. Pop four knockouts: two low on the left side (intake), one high on the
   right (fan exhaust), one low at the back (cables).
2. Drill four holes in the carrier plate, 58 x 49 mm apart, screw on the
   standoffs. Drill two holes in the box floor and bolt the plate in.
3. Spray the box and lid matte black outside. Let it dry overnight.

Evening 2 (about 3 hours)
4. Zip-tie mesh over the intake and exhaust knockouts. Mount the fan behind
   the exhaust knockout, blowing out.
5. Fit the Active Cooler to the Pi, then the Pi to the standoffs, SD card slot
   facing the open side so you can reach it with the lid off.
6. Cables in through the clamp connectors at the back: USB-C power, Ethernet
   to the router, micro-HDMI, USB audio. Leave a loop inside, zip-tie each
   cable to a tie-down mount before it reaches the Pi.
7. Strap the router to the lid, antennas up.
8. Scrawl: J R A, crossed-out words, the figure upside down. Smear raw
   pink into the black with your thumb.
9. Close the lid, run the security cable through a knockout and around
   something fixed, lock it.

Heat test before the show: over SSH, run the app for an hour and type `heat`
(installed by install.sh). Under 75 C and `throttled=0x0` is good. Above
80 C, open another intake knockout or use a bigger fan.

## Boot look (files in this folder)

| Path | What it is |
| --- | --- |
| `splash/plymouth/splash.png` | The boot image, 1920 x 1080 |
| `splash/plymouth/infinitejest.*` | Plymouth theme: fades in from black, breathes, flickers |
| `splash/make_splash.py` | Redraws the image (`--seed` for a new smear, `--title` for other words) |
| `console/` | Console palette, font, login banner, SSH prompt |
| `install.sh` | Installs all of it on the Pi |
| `preview.sh` | Shows the splash on the projector for a few seconds |
| `uninstall.sh` | Puts every changed file back |

On the Pi (over SSH from the Mac):

```bash
cd ~/read_the_room/infinite_jest/case
sudo ./install.sh     # about 2 minutes, needs internet once for apt
sudo ./preview.sh     # look at the projector
sudo reboot           # the real thing
```

Not yet tested on Baby's Pi. If the screen shows text instead of the image,
run `sudo plymouth-set-default-theme` (it should print `infinitejest`) and
check that `/boot/firmware/cmdline.txt` ends with `quiet splash ...` on one line.
