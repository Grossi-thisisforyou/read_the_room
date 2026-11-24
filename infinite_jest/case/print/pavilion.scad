// INFINITE JEST · "Pavilion" · Raspberry Pi 5 case, after Mies van der Rohe
// ---------------------------------------------------------------------------
// The Pi as an honest device, housed like a Mies pavilion: a podium slab
// floating on a recessed plinth, a curtain wall of slim vertical mullions
// (the slots between them are the ventilation), four cruciform corner
// columns, and a thin roof slab that floats above the walls on a shadow gap,
// so warm air leaves all the way round. Every port is a clean framed
// opening. Less is more; nothing is hidden that you need to reach.
//
// Two parts, both print with no supports:
//   part = "base";  // plinth, podium, walls, columns, Pi standoffs
//   part = "roof";  // print it top face down
//
//   openscad -D 'part="base"' -o pavilion_base.stl pavilion.scad
//   openscad -D 'part="roof"' -o pavilion_roof.stl pavilion.scad
//
// Access (Raspberry Pi 5 with the official Active Cooler):
//   microSD end : power button, status LEDs and microSD card, one opening
//   long side   : USB-C power, micro-HDMI 0 and 1, one opening
//   short end   : 2x USB 3, 2x USB 2, Ethernet, one opening
//   roof        : 4 countersunk M3 x 10 screws; lift it for GPIO and fan
// Hardware: 4x M2.5 x 6 mm (Pi to standoffs), 4x M3 x 10 mm countersunk
//           (roof to columns), 4x 8 mm self-adhesive rubber bumpers.
// Sizes in mm. Board coordinates: x = 0 is the microSD end, y = 0 the HDMI edge.

part = "assembly";   // "base", "roof", "assembly"
$fn = 48;

// ---- Raspberry Pi 5 -------------------------------------------------------
pcb_x = 85; pcb_y = 56; pcb_t = 1.6;
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];

// ---- the order of the building ---------------------------------------------
plinth_h  = 3;      // recessed plinth with a 45 degree shadow
podium_t  = 3;      // podium slab
standoff  = 5;      // room under the board for the microSD card
clear_top = 19;     // above the board: cooler and USB stack (16 mm)
wall      = 2;
gap       = 1;      // air between board and wall
shadow    = 3.5;    // the floating gap between wall top and roof
roof_t    = 4;

podium_z = plinth_h + podium_t;          // top of the podium
pcb_z    = podium_z + standoff;          // underside of the board
top_z    = pcb_z + pcb_t;                // top of the board
wall_z   = top_z + clear_top;            // top of the walls
roof_z   = wall_z + shadow;              // underside of the roof

// walls (outer faces)
wx0 = -gap - wall;             wx1 = pcb_x + gap + wall;
wy0 = -gap - wall;             wy1 = pcb_y + gap + wall;
// podium: wider at the port end, a terrace for the cables
terrace = 14; edge = 9;
px0 = wx0 - edge;  px1 = wx1 + terrace;
py0 = wy0 - edge;  py1 = wy1 + edge;
// roof overhang
ov = 7;
rx0 = wx0 - ov; rx1 = wx1 + ov; ry0 = wy0 - ov; ry1 = wy1 + ov;

// columns stand outside the wall corners, under the roof
col_off = 5;
cols = [[wx0 - col_off, wy0 - col_off], [wx1 + col_off, wy0 - col_off],
        [wx0 - col_off, wy1 + col_off], [wx1 + col_off, wy1 + col_off]];

// mullion rhythm
pitch = 5; slot_w = 2.2; fin_w = 1.2; fin_d = 1.4;

// openings, in board coordinates (x along the board, y across, z absolute)
open_ports = [[-2, pcb_y + 2], [top_z - 0.8, top_z + 17.2]];   // USB end: y range, z range
open_side  = [[2.5, 53], [top_z - 1.2, top_z + 8.5]];         // HDMI side: x range, z range
open_front = [[4, 42], [podium_z + 0.6, top_z + 7]];           // microSD end: y range, z range

module rect(x0, y0, x1, y1, h) { translate([x0, y0, 0]) cube([x1 - x0, y1 - y0, h]); }

module cruciform(h, s = 10, t = 2.4, core = 5) {
    translate([-s / 2, -t / 2, 0]) cube([s, t, h]);
    translate([-t / 2, -s / 2, 0]) cube([t, s, h]);
    translate([-core / 2, -core / 2, 0]) cube([core, core, h]);
}

// vertical slots along a wall from a to b (positions along the wall)
module slots(a, b, z0, z1, d = 4.4) {
    n = floor((b - a) / pitch);
    s = a + ((b - a) - n * pitch) / 2;
    for (i = [0 : n - 1]) translate([s + i * pitch + (pitch - slot_w) / 2, 0, z0]) cube([slot_w, d, z1 - z0]);
}

module fins(a, b, z0, z1) {
    n = floor((b - a) / pitch);
    s = a + ((b - a) - n * pitch) / 2;
    for (i = [0 : n]) translate([s + i * pitch - fin_w / 2, 0, z0]) cube([fin_w, fin_d, z1 - z0]);
}

module walls() {
    z0 = podium_z; z1 = wall_z;
    sz0 = podium_z + 3; sz1 = wall_z - 3;
    difference() {
        union() {
            difference() {
                rect(wx0, wy0, wx1, wy1, z1);
                translate([0, 0, -1]) rect(wx0 + wall, wy0 + wall, wx1 - wall, wy1 - wall, z1 + 2);
            }
            // the mullions, outside the wall line
            translate([0, wy0, 0]) mirror([0, 1, 0]) fins(wx0 + 4, wx1 - 4, z0, z1);          // HDMI side
            translate([0, wy1, 0]) fins(wx0 + 4, wx1 - 4, z0, z1);                             // GPIO side
            translate([wx0, 0, 0]) rotate([0, 0, 90]) fins(wy0 + 4, wy1 - 4, z0, z1);          // microSD end
            translate([wx1, 0, 0]) rotate([0, 0, 90]) mirror([0, 1, 0]) fins(wy0 + 4, wy1 - 4, z0, z1);
        }
        // ventilation slots between the mullions
        translate([0, wy0 - fin_d - 0.5, 0]) slots(wx0 + 4, wx1 - 4, sz0, sz1);
        translate([0, wy1 - wall - 0.5, 0]) slots(wx0 + 4, wx1 - 4, sz0, sz1);
        translate([wx0 + wall + 0.5, 0, 0]) rotate([0, 0, 90]) slots(wy0 + 4, wy1 - 4, sz0, sz1);
        translate([wx1 + fin_d + 0.5, 0, 0]) rotate([0, 0, 90]) slots(wy0 + 4, wy1 - 4, sz0, sz1);
        // the three port openings, cut through wall and mullions
        translate([0, 0, open_ports[1][0]]) rect(wx1 - wall - 1, open_ports[0][0], wx1 + 5, open_ports[0][1], open_ports[1][1] - open_ports[1][0]);
        translate([0, 0, open_side[1][0]])  rect(open_side[0][0], wy0 - 5, open_side[0][1], wy0 + wall + 1, open_side[1][1] - open_side[1][0]);
        translate([0, 0, open_front[1][0]]) rect(wx0 - 5, open_front[0][0], wx0 + wall + 1, open_front[0][1], open_front[1][1] - open_front[1][0]);
    }
}

module podium() {
    // plinth with a 45 degree shadow, then the slab
    hull() {
        rect(px0 + plinth_h, py0 + plinth_h, px1 - plinth_h, py1 - plinth_h, 0.01);
        translate([0, 0, plinth_h - 0.01]) rect(px0, py0, px1, py1, 0.01);
    }
    translate([0, 0, plinth_h]) rect(px0, py0, px1, py1, podium_t);
}

module base() {
    difference() {
        union() {
            podium();
            walls();
            for (c = cols) translate([c[0], c[1], podium_z - 0.01]) cruciform(roof_z - podium_z + 0.01);
            for (h = holes) translate([h[0], h[1], podium_z - 0.01]) cylinder(d = 6, h = standoff + 0.01);
        }
        for (h = holes) translate([h[0], h[1], podium_z - 2]) cylinder(d = 2.2, h = standoff + 3);
        for (c = cols) translate([c[0], c[1], roof_z - 12]) cylinder(d = 2.6, h = 13, $fn = 20);
        // air in, under the board, through the podium
        for (x = [12 : pitch : 72]) translate([x, 10, -1]) cube([slot_w, 36, podium_z + 2]);
        // zip-tie slots on the terrace (port end) and along the HDMI side
        for (y = [4, 22, 40]) translate([wx1 + 6, y, -1]) cube([2.4, 9, podium_z + 2]);
        for (x = [6, 22, 38]) translate([x, py0 + 2.5, -1]) cube([9, 2.4, podium_z + 2]);
        // bumper seats under the plinth
        for (x = [px0 + 12, px1 - 12], y = [py0 + 12, py1 - 12]) translate([x, y, -0.01]) cylinder(d = 8.6, h = 0.8);
    }
}

module roof() {
    difference() {
        translate([0, 0, roof_z]) rect(rx0, ry0, rx1, ry1, roof_t);
        for (c = cols) translate([c[0], c[1], roof_z - 1]) {
            cylinder(d = 3.4, h = roof_t + 2, $fn = 20);
            translate([0, 0, roof_t + 1 - 1.9]) cylinder(d1 = 3.4, d2 = 6.6, h = 1.91, $fn = 24);
        }
    }
}

// ---------------------------------------------------------------------------
if (part == "base") base();
else if (part == "roof") translate([0, 0, roof_z + roof_t]) mirror([0, 0, 1]) roof();
else {
    color("#e9e6df") base();
    color("#e9e6df") roof();
    color("#4a7a4a") translate([0, 0, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
    color("#2b2b2b") translate([18, 12, top_z]) cube([42, 34, 13]);                 // Active Cooler
    color("#b8b8b8") translate([pcb_x - 18, 2, top_z]) cube([21, 52, 16]);          // USB + Ethernet
}
