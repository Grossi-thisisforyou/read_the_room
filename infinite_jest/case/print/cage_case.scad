// INFINITE JEST · Raspberry Pi 5 cage case
// ------------------------------------------------------------
// A printed cage for the Pi, after Bacon's space frames and curtain
// streaks, Basquiat's scrawled caps and Baselitz's upside-down lettering.
//
// Two parts, both print flat with no supports:
//   part = "base";  // tray with cage walls, cable tie bars, screw ears
//   part = "lid";   // flat lid: curtain bars, space-frame ribs, J R A, text
//
// Export from the command line:
//   openscad -D 'part="base"' -o cage_base.stl cage_case.scad
//   openscad -D 'part="lid"'  -o cage_lid.stl  cage_case.scad
//
// Fits a Raspberry Pi 5 with the official Active Cooler fitted.
// Hardware: 4x M2.5 x 6 mm screws (Pi to standoffs, self-tapping),
//           4x M3 x 12 mm screws (lid to base, self-tapping),
//           2x wood screws or bolts through the ears (base to desk).
// All sizes in millimetres.

part = "assembly";   // "base", "lid" or "assembly" (preview only)

$fn = 40;

// ---- Raspberry Pi 5 -------------------------------------------------
pcb_x = 85;          // long side; x = 0 is the microSD end
pcb_y = 56;          // y = 0 is the USB-C / micro-HDMI edge
pcb_t = 1.6;
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];

// ---- case -----------------------------------------------------------
gap      = 1.5;      // air between board and wall
wall     = 2.4;
floor_t  = 2.4;
standoff = 5;        // board sits this far above the floor
above    = 24;       // room above the board for cooler and USB stack
inner_x  = pcb_x + gap + 1;   // port end overhangs anyway
inner_y  = pcb_y + 2 * gap;
pcb_z    = floor_t + standoff;          // underside of the board
wall_h   = pcb_z + pcb_t + above;       // top of the walls
outer_x  = inner_x + 2 * wall;
outer_y  = inner_y + 2 * wall;
boss_d   = 8;        // corner bosses for the lid screws

// cage bars
bar      = 3;        // bar width
slot     = 4;        // gap between bars: air in, fingers out
rail_bot = pcb_z + 1; // solid band at the bottom of every wall
rail_top = 4;        // solid band at the top

// floor extensions
ext_port = 20;       // beyond the port end: cable tie bars + screw ear
ext_sd   = 14;       // beyond the microSD end: screw ear + lock slot
ext_side = 14;       // beyond the HDMI side: cable tie bars

lid_t    = 3;
rib_h    = 2;        // space-frame ribs stand this far above the lid

// board origin inside the case (outer coordinates)
bx = wall + gap;
by = wall + gap;

module rrect(x, y, h, r = 2) {
    linear_extrude(h) offset(r) offset(-r) square([x, y]);
}

// ---------------------------------------------------------------------
// BASE
// ---------------------------------------------------------------------
module bars_cut(len, h0, h1, axis) {
    // vertical slots along a wall of length len
    n = floor((len - bar) / (bar + slot));
    start = (len - (n * (bar + slot) - slot)) / 2;
    for (i = [0 : n - 1]) {
        p = start + i * (bar + slot);
        if (axis == "x") translate([p, -1, h0]) cube([slot, wall + 2, h1 - h0]);
        else             translate([-1, p, h0]) cube([wall + 2, slot, h1 - h0]);
    }
}

module floor_plate() {
    difference() {
        translate([-ext_sd, -ext_side, 0])
            rrect(outer_x + ext_sd + ext_port, outer_y + ext_side, floor_t, 4);
        // screw ears (countersunk from above)
        for (p = [[-ext_sd / 2, outer_y / 2], [outer_x + ext_port - 6, outer_y - 8]])
            translate([p[0], p[1], -1]) {
                cylinder(d = 4.5, h = floor_t + 2);
                translate([0, 0, floor_t + 1 - 2.5]) cylinder(d1 = 4.5, d2 = 9, h = 2.5);
            }
        // security cable slot at the microSD end
        translate([-ext_sd + 3, 8, -1]) rrect(6, 14, floor_t + 2, 1.5);
        // zip-tie slots: port end (two rows) and HDMI side (one row)
        for (y = [6, 22, 38]) for (dx = [6, 14])
            translate([outer_x + dx, y, -1]) cube([3, 6, floor_t + 2]);
        for (x = [14, 30, 46]) for (dy = [3, 10])
            translate([bx + x, -dy - 3, -1]) cube([6, 3, floor_t + 2]);
        // words on the underside, mirrored so they read from below
        translate([outer_x / 2, outer_y / 2, -0.01]) mirror([1, 0, 0]) linear_extrude(0.8) {
            translate([0, 8])  text("DARK DATA", size = 6, font = "Liberation Sans:style=Bold", halign = "center");
            translate([0, -2]) text("CUSTOM MADE INTIMACY", size = 3.6, font = "Liberation Sans:style=Bold", halign = "center");
            translate([0, -10]) text("IN ART WE TRUST", size = 3.6, font = "Liberation Sans:style=Bold", halign = "center");
        }
    }
}

module walls() {
    difference() {
        union() {
            difference() {
                rrect(outer_x, outer_y, wall_h, 2);
                translate([wall, wall, -1]) cube([inner_x, inner_y, wall_h + 2]);
            }
            // corner bosses outside the walls, like bolted steel
            for (x = [0, outer_x]) for (y = [0, outer_y])
                translate([x, y, 0]) cylinder(d = boss_d, h = wall_h);
        }
        // lid screw pilots (M3 self-tapping)
        for (x = [0, outer_x]) for (y = [0, outer_y])
            translate([x, y, wall_h - 14]) cylinder(d = 2.6, h = 15);

        // cage bars on the long sides and the microSD end
        translate([0, 0, 0])              bars_cut(outer_x, rail_bot, wall_h - rail_top, "x");
        translate([0, outer_y - wall, 0]) bars_cut(outer_x, rail_bot, wall_h - rail_top, "x");
        translate([0, 0, 0])              bars_cut(outer_y, rail_bot, wall_h - rail_top, "y");

        // port end: one open window for USB x4 and Ethernet
        translate([outer_x - wall - 1, wall + 1, pcb_z + pcb_t - 0.5])
            cube([wall + 2, inner_y - 2, 17.5]);
        // USB-C + 2x micro-HDMI window on the y = 0 side
        translate([bx + 2, -1, pcb_z + pcb_t - 1]) cube([50, wall + 2, 9]);
        // microSD slot under the board at x = 0
        translate([-1, by + 18, floor_t + 1]) cube([wall + 2, 20, pcb_z - floor_t]);
    }
}

module standoffs() {
    for (h = holes) translate([bx + h[0], by + h[1], 0]) difference() {
        cylinder(d = 6, h = pcb_z);
        translate([0, 0, floor_t]) cylinder(d = 2.2, h = pcb_z);  // M2.5 self-tapping
    }
}

module base() {
    floor_plate();
    walls();
    standoffs();
}

// ---------------------------------------------------------------------
// LID
// ---------------------------------------------------------------------
margin = 7;               // solid frame around the opening
text_band = 11;           // wider frame on one side for the lettering

module lid_outline(h) {
    hull() for (x = [0, outer_x]) for (y = [0, outer_y])
        translate([x, y, 0]) cylinder(d = boss_d, h = h);
}

module crown2d(w, h) {
    // Basquiat's three-point crown, slightly off-kilter
    polygon([[0, 0], [w * 0.06, h * 0.92], [w * 0.28, h * 0.42], [w * 0.5, h * 1.08],
             [w * 0.72, h * 0.40], [w * 0.95, h], [w, 0]]);
}

module scrawl_text(str, size) {
    // each letter its own tilt and baseline, like hand lettering
    tilts = [-6, 4, -3, 7, -5, 2, -7, 5, -2, 6, -4, 3, -6, 4];
    lifts = [0.0, 0.6, -0.4, 0.3, -0.6, 0.5, 0.0, -0.3, 0.6, -0.5, 0.2, 0.0, 0.4, -0.2];
    for (i = [0 : len(str) - 1])
        translate([i * size * 0.78, lifts[i % len(lifts)] * size * 0.25])
            rotate(tilts[i % len(tilts)])
                text(str[i], size = size * (0.9 + 0.2 * ((i * 7) % 5) / 4),
                     font = "Liberation Sans:style=Bold", halign = "center");
}

module lid() {
    ox = margin; oy = text_band;                 // opening origin
    w = outer_x - 2 * margin; d = outer_y - margin - text_band;
    difference() {
        lid_outline(lid_t);
        // big opening
        translate([ox, oy, -1]) rrect(w, d, lid_t + 2, 2);
        // screw holes, countersunk from the top
        for (x = [0, outer_x]) for (y = [0, outer_y]) translate([x, y, -1]) {
            cylinder(d = 3.4, h = lid_t + 2);
            translate([0, 0, lid_t + 1 - 1.8]) cylinder(d1 = 3.4, d2 = 6.4, h = 1.8);
        }
    }
    // Bacon's curtain: thin vertical streaks across the opening
    intersection() {
        translate([ox, oy, 0]) cube([w, d, lid_t]);
        for (x = [ox + 2 : 5.5 : ox + w]) translate([x, oy - 1, 0]) cube([2, d + 2, lid_t]);
    }
    // Bacon's space frame: a box in perspective, as raised ribs
    fx0 = ox + 8; fy0 = oy + 5; fx1 = ox + w - 26; fy1 = oy + d - 13;
    dx = 18; dy = 9;
    front = [[fx0, fy0], [fx1, fy0], [fx1, fy1], [fx0, fy1]];
    back  = [for (p = front) [p[0] + dx, p[1] + dy]];
    module rib(a, b) hull() { translate(a) cylinder(d = 2.6, h = lid_t + rib_h, $fn = 12);
                              translate(b) cylinder(d = 2.6, h = lid_t + rib_h, $fn = 12); }
    for (i = [0 : 3]) {
        rib(front[i], front[(i + 1) % 4]);
        rib(back[i],  back[(i + 1) % 4]);
        rib(front[i], back[i]);
    }
    // J R A, raised and scrawled, sitting on the frame's top edge
    translate([fx0 + 10, fy1 + dy + 0.5, 0]) linear_extrude(lid_t + rib_h + 1)
        scrawl_text("J R A", 8);
    // lettering on the wide band, upside down after Baselitz
    translate([outer_x / 2 + 30, text_band / 2 + 2.5, lid_t - 0.01]) rotate(180)
        linear_extrude(1.2) scrawl_text("INFINITE JEST", 6.2);
    translate([outer_x - margin - 1, 3, lid_t - 0.01]) rotate(180)
        linear_extrude(1.2) text("©", size = 5, font = "Liberation Sans:style=Bold", halign = "center");
}

// ---------------------------------------------------------------------
if (part == "base") base();
else if (part == "lid") lid();
else {
    base();
    color("#d9826b") translate([bx, by, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
    translate([0, 0, wall_h + 0.2]) lid();
}
