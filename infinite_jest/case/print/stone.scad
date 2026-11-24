// INFINITE JEST · "Stone" · Raspberry Pi 5 case: one tray, two shells
// ---------------------------------------------------------------------------
// A geometric pebble: about 30 flat facets, softly rounded where they meet,
// and one flat bottom. It splits into three printed parts:
//
//   part = "tray";    // flat bottom, holds the Pi, carries the click rim
//   part = "work";    // shell for working: breathes, every connector open
//   part = "travel";  // shell for the bag: closed, protects the ports
//
// Print the tray bottom down (no supports) and both shells rim down, with tree
// supports from the build plate only: they touch just the inside of the crown.
//
// Either shell clicks onto the tray: the tray's rim has a groove, the shell
// has small ridges that snap into it. Pull the shell straight up to open.
//
//   openscad -D 'part="tray"'   -o stone_tray.stl   stone.scad
//   openscad -D 'part="work"'   -o stone_work.stl   stone.scad
//   openscad -D 'part="travel"' -o stone_travel.stl stone.scad
//
// Raspberry Pi 5 with the official Active Cooler. Board coordinates below:
// the board is centred, x = -42.5 is the microSD end, y = -28 the HDMI edge.
// Hardware: 4x M2.5 x 6 mm screws (self-tapping, or into heat-set inserts
// with threads = "insert"), 4x 8 mm rubber bumpers. Sizes in mm.

part = "assembly";   // "tray", "work", "travel", "assembly", "travel_assembly", "exploded", "fitcheck"
seed = 2026;         // change for a differently cut stone
$fn = 24;

// ---- the stone --------------------------------------------------------------
A = 64; B = 50; C = 30;       // ellipsoid the facets are tangent to
ZC = 16;                      // its centre height
round_r = 10;                 // how soft the facet edges are: sea-washed
wall = 2.2;

nA = 14; nB = 14;             // lower ring of facets (near vertical), upper ring (shoulders)
rnd = rands(0, 1, 4 * (nA + nB), seed);
// facets wander in direction and are cut to different depths, so some planes are
// broad and some are narrow slivers between them
sides = concat(
    [for (i = [0 : nA - 1]) let(az = i * 360 / nA + (rnd[i] - 0.5) * 30,
                                el = -16 + rnd[nA + i] * 26)            // -16 .. +10 degrees
        [cos(el) * cos(az), cos(el) * sin(az), sin(el)]],
    [for (i = [0 : nB - 1]) let(az = (i + 0.5) * 360 / nB + (rnd[2 * nA + i] - 0.5) * 30,
                                el = 32 + rnd[2 * nA + nB + i] * 14)    // 32 .. 46 degrees
        [cos(el) * cos(az), cos(el) * sin(az), sin(el)]]);
// the crown: a few low facets, each tilted its own way, so the top is uneven
nT = 4;
rt = rands(0, 1, 3 * nT, seed + 1);
crown = [for (i = [0 : nT - 1]) let(az = i * 360 / nT + 20 + (rt[i] - 0.5) * 70,
                                    el = 70 + rt[nT + i] * 13)              // 70 .. 83 degrees
        [cos(el) * cos(az), cos(el) * sin(az), sin(el)]];
normals = concat(sides, crown);
cuts = concat([for (i = [0 : nA + nB - 1]) pow(rnd[2 * (nA + nB) + i], 2) * (i < nA ? 4 : 6)],   // 0 .. 4-6 mm deeper
              [for (i = [0 : nT - 1]) rt[2 * nT + i] * 2.5]);

function support(n) = n[2] * ZC + sqrt(pow(A * n[0], 2) + pow(B * n[1], 2) + pow(C * n[2], 2));

module halfspace(n, d) {
    // everything on the inner side of the plane n . p = d
    L = 400;
    th = acos(n[2]); ph = atan2(n[1], n[0]);
    rotate([0, 0, ph]) rotate([0, th, 0]) translate([-L / 2, -L / 2, d - L]) cube(L);
}

// the stone as an intersection of 32 half-spaces and the flat bottom, pulled in by s
module poly(s = 0, e = 0) {
    intersection() {
        intersection_for (i = [0 : len(normals) - 1]) halfspace(normals[i], support(normals[i]) - cuts[i] - s);
        translate([-200, -200, s - e]) cube([400, 400, 200]);   // flat bottom
    }
}

// the rounded stone pulled in by s: exact inward offset of the sea-washed surface
module off(s = 0) {
    // the flat bottom meets the rounding at 45 degrees, not tangent, so the
    // first layers on the bed do not overhang
    e = round_r * (1 - cos(45));
    if (s < round_r) intersection() {
        minkowski() { poly(round_r, e); sphere(round_r - s, $fn = 28); }
        translate([-200, -200, s]) cube([400, 400, 200]);
    }
    else poly(s);
}
module stone() { off(0); }
module cavity() { off(wall); }

// ---- the Raspberry Pi 5 ------------------------------------------------------
pcb_x = 85; pcb_y = 56; pcb_t = 1.6;
bx = -pcb_x / 2; by = -pcb_y / 2;               // board corner (microSD end, HDMI edge)
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];
floor_t = 2.4; standoff = 4.2;
pcb_z = floor_t + standoff;                      // underside of the board
top_z = pcb_z + pcb_t;
threads = "self";
m25_hole = threads == "insert" ? 3.6 : 2.2;

// ---- the split and the click rim ---------------------------------------------
split = pcb_z + 0.4;          // tray / shell seam, just under the board
rim_h = 6; rim_t = 1.8; clr = 0.25;
groove_z = split + 3; groove_h = 1.4; groove_d = 0.7;
bump_d = 0.55;

// openings, board coordinates -> stone coordinates
function X(x) = bx + x;
function Y(y) = by + y;
open_ports = [[Y(-2.5), Y(pcb_y + 2.5)], [top_z - 1.4, top_z + 17.8]];   // USB + Ethernet end
open_side  = [[X(2), X(53.5)], [top_z - 1.6, top_z + 9]];                 // USB-C, HDMI 0, HDMI 1
open_front = [[Y(3.5), Y(42.5)], [top_z - 1.2, top_z + 7.5]];             // power button, LEDs
sd_slot    = [[Y(17), Y(39)], [floor_t + 1, split + 0.5]];               // microSD, in the tray

// where the rim must stay out of the way of the connectors
module rim_gaps() {
    translate([X(pcb_x) - 4, -100, 0]) cube([100, 200, 100]);                       // whole port end
    translate([X(0.5), -100, 0]) cube([X(55) - X(0.5), 100 - 25, 100]);              // HDMI side span
    translate([-100, open_front[0][0] - 1, 0]) cube([100 + X(0) + 3, open_front[0][1] - open_front[0][0] + 2, 100]);
}

module ring(s_out, s_in, z0, z1) {
    intersection() {
        difference() { off(s_out); off(s_in); }
        translate([-200, -200, z0]) cube([400, 400, z1 - z0]);
    }
}

// ---- marks -----------------------------------------------------------------------
mark = "J R A";
font_mark = "Inter Display:style=SemiBold";
font_small = "Inter:style=Bold";
// two fine channels that cross on the crown and under the tray, one the long
// way and one across, for two rubber bands or hair ties that keep the stone
// shut in a bag
band_w = 3.5; band_d = 0.9;
module band_groove() intersection() {
    union() {
        translate([-200, -band_w / 2, -1]) cube([400, band_w, 200]);
        translate([-band_w / 2, -200, -1]) cube([band_w, 400, 200]);
    }
    difference() { translate([-200, -200, -1]) cube(400); off(band_d); }
}

module label(t, size, font = font_small) text(t, size = size, font = font, halign = "center", valign = "center");

// under the tray, as read when you turn the stone over
module bottom_text() {
    // four fields between the arms of the band cross
    translate([-18, 30]) label(mark, 4.5, font_mark);
    translate([18, 30]) label("INFINITE JEST", 3.2);
    translate([-19, -22]) label("Raspberry Pi 5", 2.8);
    translate([-19, -27.5]) label("16 GB", 2.8);
    translate([19, -22]) label("return to", 2.8);
    translate([19, -27.5]) label("Jasper Engelhardt", 2.8);
    translate([19, -33]) label("jasperengelhardt.com", 2.8);
}

// small mark pressed into the top facet of each shell
// it follows the tilted crown facet it lands on
module top_mark() intersection() {
    translate([-24, -20, 0]) linear_extrude(100) label(mark, 3.6, font_mark);
    difference() { translate([-200, -200, 20]) cube(400); off(0.5); }
}
// and a raised one on the ceiling inside each shell, read from below
// and a raised one on the inside wall at the microSD end, read from inside
module inner_mark() intersection() {
    translate([-100, 0, 23]) rotate([90, 0, 90]) linear_extrude(70) label(mark, 5, font_mark);
    difference() { off(wall); off(wall + 0.6); }
}

// ---- tray ----------------------------------------------------------------------
module tray() {
    difference() {
        union() {
            difference() {
                intersection() { stone(); translate([-200, -200, -1]) cube([400, 400, split + 1]); }
                // inside the tray the wall is as thick as the rim above it, so the rim stands on it
                intersection() { off(wall + clr + rim_t); translate([-200, -200, floor_t]) cube([400, 400, 100]); }
            }
            // the click rim, standing up inside the shell line
            difference() {
                ring(wall + clr, wall + clr + rim_t, split - 0.01, split + rim_h);
                rim_gaps();
            }
            // Pi standoffs with braced feet
            for (h = holes) translate([X(h[0]), Y(h[1]), floor_t - 0.01]) {
                cylinder(d = 6.5, h = standoff + 0.01);
                cylinder(d1 = 10, d2 = 6.5, h = 1.8);
            }
        }
        // keep-out around the board edge (1 mm), so the rim never touches it
        translate([bx - 1, by - 1, pcb_z - 0.6]) cube([pcb_x + 2, pcb_y + 2, 30]);
        // groove in the rim for the shell's ridges
        ring(wall + clr - 1, wall + clr + groove_d, groove_z, groove_z + groove_h);
        for (h = holes) translate([X(h[0]), Y(h[1]), 1]) cylinder(d = m25_hole, h = 20);
        // microSD slot
        translate([-100, sd_slot[0][0], sd_slot[1][0]]) cube([100 + X(0) - 1, sd_slot[0][1] - sd_slot[0][0], 20]);
        // air in, under the board
        for (x = [-28, -22, -16, -10, -4, 4, 10, 16, 22, 28]) translate([x - 1.2, -16, -1]) cube([2.4, 32, wall + clr + rim_t + 2]);   // through the floor
        // bumper seats and the name, underneath
        for (x = [-41, 41], y = [-25, 25]) translate([x, y, -0.01]) cylinder(d = 8.6, h = 0.8);
        translate([0, 0, -0.01]) mirror([1, 0, 0]) linear_extrude(0.6) bottom_text();
        band_groove();
    }
}

// ---- shells ----------------------------------------------------------------------
module shell_raw() {
    difference() {
        intersection() { stone(); translate([-200, -200, split]) cube([400, 400, 100]); }
        cavity();
        top_mark();
        band_groove();
    }
    inner_mark();
    // ridges that snap into the rim's groove (only where the rim exists)
    difference() {
        ring(wall - 0.01, wall + bump_d, groove_z + 0.15, groove_z + groove_h - 0.15);
        rim_gaps();
        // leave the corners free so the walls can flex
        for (sx = [-1, 1], sy = [-1, 1]) translate([sx * 50 - 12, sy * 36 - 12, 0]) cube([24, 24, 100]);
    }
}

module vents() {
    // breathing: parallel slits over the fan, cut straight down through the roof
    for (x = [-22 : 4.4 : 22]) translate([x - 1.1, -15, split + 22]) cube([2.2, 30, 60]);
    // and a band of slits along the GPIO side, above the rim
    for (x = [-36 : 5 : 36]) translate([x - 1.1, 20, split + rim_h + 1]) cube([2.2, 40, 8]);
}

module work() {
    difference() {
        shell_raw();
        vents();
        translate([0, open_ports[0][0], open_ports[1][0]]) translate([X(pcb_x) - 3, 0, 0])
            cube([100, open_ports[0][1] - open_ports[0][0], open_ports[1][1] - open_ports[1][0]]);
        translate([open_side[0][0], -100, open_side[1][0]])
            cube([open_side[0][1] - open_side[0][0], 100 + Y(0) + 2, open_side[1][1] - open_side[1][0]]);
        translate([-100, open_front[0][0], open_front[1][0]])
            cube([100 + X(0) + 2, open_front[0][1] - open_front[0][0], open_front[1][1] - open_front[1][0]]);
    }
}

module travel() { shell_raw(); }

// ---------------------------------------------------------------------------
if (part == "tray") tray();
// shells print rim down; tree supports from the bed carry the inside of the crown
else if (part == "work") translate([0, 0, -split]) work();
else if (part == "travel") translate([0, 0, -split]) travel();
else if (part == "fitcheck") {
    // must come out empty: board, cooler and USB block against the tray and work shell
    intersection() {
        union() { tray(); work(); travel(); }
        union() {
            translate([bx, by, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
            translate([bx + 18, by + 12, top_z]) cube([42, 34, 13]);
            translate([bx + pcb_x - 18, by + 2, top_z]) cube([21, 52, 16]);
        }
    }
}
else if (part == "exploded") {
    color("#2a2a2c") tray();
    color("#4a7a4a") translate([bx, by, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
    color("#1c1c1c") translate([bx + 18, by + 12, top_z]) cube([42, 34, 13]);
    color("#b8b8b8") translate([bx + pcb_x - 18, by + 2, top_z]) cube([21, 52, 16]);
    color("#3a3a3e") translate([0, 0, 45]) work();
    color("#55555a") translate([0, 130, 0]) travel();
}
else {
    color("#2a2a2c") tray();
    color("#3a3a3e") if (part == "travel_assembly") travel(); else work();
    color("#4a7a4a") translate([bx, by, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
}
