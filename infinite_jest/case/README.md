# The shell: case and boot look

Two halves of one object: the physical housing for the Raspberry Pi 5, and what
the projector shows while the Pi boots. Both follow the piece's references:
Bacon's cage and smeared flesh, Baselitz's upside-down figures, Basquiat's
crown, scrawled caps and crossed-out words. Deep, dark, industrial.

Concept drawings, materials and the recommended build are on the case page:
https://claude.ai/artifact/K8ieND4PyYRjzZzYYN21oY (private to Baby). This folder holds the files for the Pi.

## Recommended case: the junction box

A steel electrical pull box, 12 x 12 x 4 in, painted matte black and scrawled
with oil stick, lettered upside down. The Pi sits inside on standoffs, the
Linksys router is strapped on top with its antennas up (Wi-Fi does not get out
of a steel box, so the router must stay outside). Only low-voltage cables go
in: nothing inside is above 12 V, so it is safe to touch.

Why this one for Nov 23: everything comes from one hardware store trip, it
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
| - | Matte black spray paint, oil sticks (red, flesh pink, bone white), a white paint marker | Finish. Markal Paintstiks are the welders' oil sticks; Basquiat used oil stick too. |

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
8. Scrawl: crown, crossed-out words, (c), the figure upside down. Smear raw
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
