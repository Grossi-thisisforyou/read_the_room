// INFINITE JEST · "The Black Box" · Raspberry Pi 5 case, third design
// ---------------------------------------------------------------------
// A faceted black stone, like a lump of obsidian or a meteorite, split
// along its horizon. The top floats a few millimetres above the bottom,
// so a thin line of light from the Pi runs all the way round it, and a
// jagged crack across the top glows too. A flight recorder for dark data.
//
// Two parts, both print with no supports:
//   part = "bowl";  // bottom: foot down. Pi standoffs, pillars, cable notches
//   part = "dome";  // top: print it rim down (the flat cut on the bed)
//
//   openscad -D 'part="bowl"' -o black_box_bowl.stl black_box.scad
//   openscad -D 'part="dome"' -o black_box_dome.stl black_box.scad
//
// Use: screw the Pi in, plug every cable, lay the cables in the notches,
// then put the dome on the three pillars and screw it down.
// Hardware: 4x M2.5 x 6 mm (Pi), 3x M3 x 16 mm pan head (dome to pillars,
//           dropped down the three holes in the top with a long screwdriver).
// Fits a Raspberry Pi 5 with the official Active Cooler. Sizes in mm.

part = "assembly";   // "bowl", "dome", "assembly" (preview)
seed = 1312;         // change for a different stone

// ---- the stone ------------------------------------------------------------
rx = 90; ry = 72; rz = 72;    // ellipsoid radii
cz = 40;                      // centre height: the foot is cut flat at z = 0
ze = 46;                      // horizon: where the stone splits
gap = 7;                      // the line of light
wall = 3;
jitter = 0.13;                // how rough the facets are
n_lat = 5; n_lon = 10;        // facet density

// facet points on a jittered ellipsoid
r = rands(1 - jitter, 1 + jitter, n_lat * n_lon + 2, seed);
pts = concat(
    [[0, 0, cz + rz * r[0]], [0, 0, cz - rz * r[1]]],
    [for (i = [1 : n_lat], j = [0 : n_lon - 1])
        let(th = 180 * i / (n_lat + 1),
            ph = 360 * j / n_lon + (i % 2) * 180 / n_lon,
            k  = r[2 + (i - 1) * n_lon + j])
        [rx * k * sin(th) * cos(ph), ry * k * sin(th) * sin(ph), cz + rz * k * cos(th)]]);

module stone(shrink = 0) {
    // convex hull of the points; shrink pulls every point toward the centre
    hull() for (p = pts) {
        d = norm([p[0] / rx, p[1] / ry, (p[2] - cz) / rz]);
        s = 1 - shrink / (min(rx, ry, rz) * d);
        translate([p[0] * s, p[1] * s, cz + (p[2] - cz) * s]) cube(0.01, center = true);
    }
}

module shell() { difference() { stone(); stone(wall); } }

// ---- Raspberry Pi 5 placement ---------------------------------------------
pcb_x = 85; pcb_y = 56; pcb_t = 1.6;
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];
floor_t = 3;
standoff = 6;
pi_x0 = -28;                  // board spans x -28 .. 57: ports face +x (back)
pi_y0 = -42;                  // board spans y -42 .. 14: HDMI edge faces -y
pcb_z = floor_t + standoff;

pillars = [[-52, 28], [-52, -30], [40, 36]];

// ---- bottom -----------------------------------------------------------------
module bowl() {
    difference() {
        union() {
            intersection() {
                union() {
                    shell();
                    // solid floor
                    intersection() { stone(); translate([-200, -200, 0]) cube([400, 400, floor_t]); }
                    // pillars that carry the dome
                    for (p = pillars) translate([p[0], p[1], 0]) cylinder(d = 11, h = ze + gap, $fn = 6);
                }
                translate([-200, -200, 0]) cube([400, 400, ze + gap]);
            }
            // Pi standoffs
            for (h = holes) translate([pi_x0 + h[0], pi_y0 + h[1], 0]) cylinder(d = 6.5, h = pcb_z, $fn = 24);
        }
        // shell above the horizon belongs to the dome; pillars stay
        difference() {
            translate([-200, -200, ze]) cube([400, 400, 100]);
            for (p = pillars) translate([p[0], p[1], 0]) cylinder(d = 11.2, h = ze + gap, $fn = 6);
        }
        for (p = pillars) translate([p[0], p[1], ze - 12]) cylinder(d = 2.6, h = 30, $fn = 16);
        for (h = holes) translate([pi_x0 + h[0], pi_y0 + h[1], 1]) cylinder(d = 2.2, h = pcb_z, $fn = 16);
        // cable notches from the rim down: ports at the back, HDMI + power on the side
        translate([46, -46, pcb_z - 1]) cube([60, 62, 60]);
        translate([-24, -100, pcb_z + pcb_t - 1]) cube([56, 60, 60]);
        // air in, under the board
        for (x = [-18 : 10 : 42]) translate([x, -34, -1]) cube([4, 40, floor_t + 2]);
        // words under the foot, mirrored
        translate([0, 18, -0.01]) mirror([1, 0, 0]) linear_extrude(0.8) {
            text("DARK DATA", size = 9, font = "Liberation Sans:style=Bold", halign = "center");
            translate([0, -12]) text("CUSTOM MADE INTIMACY", size = 5, font = "Liberation Sans:style=Bold", halign = "center");
            translate([0, -60]) text("J R A", size = 6, font = "Liberation Sans:style=Bold", halign = "center");
        }
    }
}

// ---- top --------------------------------------------------------------------
// the crack: a jagged line across the top, cut straight down
crack = [[-60, 18], [-38, 6], [-30, 22], [-8, -4], [4, 10], [24, -14], [34, 0], [58, -20]];

module dome_raw() {
    // the stone above the horizon, lifted by the gap. It is solid in the
    // model; the slicer fills it with sparse infill, so the roof needs no
    // supports and the top stays heavy and stone-like.
    translate([0, 0, gap]) intersection() {
        stone();
        translate([-200, -200, ze]) cube([400, 400, 200]);
    }
}

module dome() {
    difference() {
        dome_raw();
        for (p = pillars) translate([p[0], p[1], 0]) {
            cylinder(d = 3.4, h = 300, $fn = 16);
            // deep counterbore so a short screw reaches: the head sits 8 mm above the rim
            translate([0, 0, ze + gap + 8]) cylinder(d = 7, h = 300, $fn = 24);
        }
        // the glowing crack, cut all the way through so the Pi's light comes up it
        for (i = [0 : len(crack) - 2])
            hull() {
                translate([crack[i][0], crack[i][1], ze + gap - 1]) cylinder(d = 3, h = 100, $fn = 8);
                translate([crack[i + 1][0], crack[i + 1][1], ze + gap - 1]) cylinder(d = 3, h = 100, $fn = 8);
            }
    }
}

// ---------------------------------------------------------------------------
if (part == "bowl") bowl();
else if (part == "fitcheck")  // anything left here sticks out of the stone
    difference() { translate([pi_x0 - 1, pi_y0 - 1, pcb_z]) cube([pcb_x + 2, pcb_y + 2, 20]); stone(wall); }
else if (part == "dome") translate([0, 0, -(ze + gap)]) dome();   // flat cut at z = 0 for printing
else {
    color("#242122") bowl();
    color("#242122") dome();
    color("#4a7a4a") translate([pi_x0, pi_y0, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
    color("#ff5a4a") intersection() {   // light coming up the crack
        translate([0, 0, gap + 0.3]) stone();
        for (i = [0 : len(crack) - 2]) hull() {
            translate([crack[i][0], crack[i][1], ze + gap]) cylinder(d = 2.8, h = 100, $fn = 8);
            translate([crack[i + 1][0], crack[i + 1][1], ze + gap]) cylinder(d = 2.8, h = 100, $fn = 8);
        }
    }
    color("#ff5a4a") intersection() { stone(wall + 1); translate([-200, -200, ze + 0.5]) cube([400, 400, gap - 1]); }  // the light
}
