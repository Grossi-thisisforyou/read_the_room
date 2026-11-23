// INFINITE JEST · "The Wall Box" · hide the Raspberry Pi 5 in plain sight
// ---------------------------------------------------------------------
// A plain white surface-mount electrical box, the kind bolted onto walls in
// every school. A real, store-bought 3-gang keystone wall plate screws onto
// the front, with real HDMI, Ethernet and USB keystone couplers in it, so
// the projector, router and speaker cables plug into the wall like any AV
// plate. The Pi hides behind it. Nothing about it says "art".
//
// One part, prints back-down with no supports:
//   openscad -D 'part="box"' -o wall_box.stl wall_box.scad
//
// Buy (hardware store or Amazon):
//   1x 3-gang keystone wall plate, white (e.g. 6 or 9 port), with its screws
//   keystone couplers: 1x HDMI, 1x Cat6, 1x USB-A, blanks for the rest
//   short cables inside: 30 cm micro-HDMI to HDMI, 30 cm Cat6, 30 cm USB
//   4x M2.5 x 6 mm self-tapping screws (Pi), 4 wall screws or VHB tape
// The Pi's power cable leaves through the slot in the bottom to the outlet.
// Sizes in mm. All plate screw positions follow the US wall plate standard.

part = "assembly";   // "box" or "assembly"
$fn = 40;

// ---- box -----------------------------------------------------------------
gangs   = 3;
gang_dx = 46.04;          // 1.812 in between gang centres
screw_dy = 41.66;         // plate screws are 3.281 in apart vertically
plate_w = 162.1;          // 3-gang plate 6.38 x 4.5 in
plate_h = 114.3;
reveal  = 4;              // the box shows this much around the plate
W = plate_w + 2 * reveal; // about 170
H = plate_h + 2 * reveal; // about 122
D = 64;                   // depth off the wall (a "deep" surface box)
wall = 2.5;
back = 3;
r = 5;                    // corner radius

// ---- Pi 5 -----------------------------------------------------------------
pcb_x = 85; pcb_y = 56; pcb_t = 1.6;
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];
standoff = 5;
pi_x0 = -W / 2 + wall + 22;     // board left edge (microSD end)
pi_y0 = -pcb_y / 2;             // centred vertically; HDMI edge at the bottom

module rbox(w, h, d, rr) {
    linear_extrude(d) offset(rr) offset(-rr) square([w, h], center = true);
}

module box() {
    difference() {
        union() {
            difference() {
                rbox(W, H, D, r);
                translate([0, 0, back]) rbox(W - 2 * wall, H - 2 * wall, D, r - wall);
            }
            // plate screw bosses (6-32 thread-forming), from the back up to the rim
            for (g = [0 : gangs - 1], s = [-1, 1])
                translate([(g - (gangs - 1) / 2) * gang_dx, s * screw_dy, 0]) cylinder(d = 8, h = D);
            // Pi standoffs
            for (h = holes) translate([pi_x0 + h[0], pi_y0 + h[1], 0]) cylinder(d = 6.5, h = back + standoff);
        }
        for (g = [0 : gangs - 1], s = [-1, 1])
            translate([(g - (gangs - 1) / 2) * gang_dx, s * screw_dy, back + 4]) cylinder(d = 2.8, h = D);
        for (h = holes) translate([pi_x0 + h[0], pi_y0 + h[1], 1]) cylinder(d = 2.2, h = 20);
        // wall mounting holes, countersunk from inside
        for (p = [[-W / 2 + 14, 0], [W / 2 - 14, 0]]) translate([p[0], p[1], -1]) {
            cylinder(d = 4.5, h = back + 2);
            translate([0, 0, back + 1 - 2.5]) cylinder(d1 = 4.5, d2 = 9, h = 2.5);
        }
        // power cable slot in the bottom wall, near the back (faces the outlet)
        translate([-W / 2 + 30, -H / 2 - 1, back]) cube([14, wall + 2, 9]);
        // air: slots in the bottom (in) and top (out), close to the wall where nobody looks
        for (x = [-60 : 10 : 60]) {
            translate([x, -H / 2 - 1, back + 14]) cube([4, wall + 2, 22]);
            translate([x, H / 2 - wall - 1, back + 14]) cube([4, wall + 2, 22]);
        }
    }
}

// ---------------------------------------------------------------------------
if (part == "box") box();
else {
    color("#f2f0ea") box();
    color("#4a7a4a") translate([pi_x0, pi_y0, back + standoff]) cube([pcb_x, pcb_y, pcb_t]);
    color("#3c3c3c") translate([pi_x0 + 20, pi_y0 + 12, back + standoff + pcb_t]) cube([40, 34, 14]);  // cooler
    // the bought wall plate, ghosted
    color("#ffffff", 0.85) translate([0, 0, D]) difference() {
        rbox(plate_w, plate_h, 6, 3);
        for (g = [0 : gangs - 1], k = [-1, 0, 1])
            translate([(g - (gangs - 1) / 2) * gang_dx - 7.5, k * 22 - 8, -1]) cube([15, 16.5, 8]);
    }
}
