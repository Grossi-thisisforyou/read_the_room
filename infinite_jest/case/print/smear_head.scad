// INFINITE JEST · "The Smear" · Raspberry Pi 5 case, alternative design
// ---------------------------------------------------------------------
// A head sliced into thin vertical fins. Each fin is shifted sideways a
// little more than the last, so the head reads as motion blur frozen in
// plastic: from the front it resolves into a face, from any angle it
// smears. The mouth is wide open in a scream, and the Pi glows inside it.
// The gaps between fins are the ventilation.
//
// Two parts, both print with no supports:
//   part = "head";  // base plate + fins + tie rods (fins stand upright)
//   part = "sled";  // tray the Pi screws onto; it slides into the mouth
//
//   openscad -D 'part="head"' -o smear_head.stl smear_head.scad
//   openscad -D 'part="sled"' -o smear_sled.stl smear_head.scad
//
// Hardware: 4x M2.5 x 6 mm self-tapping (Pi to sled),
//           2x M3 x 10 mm self-tapping (sled to base),
//           2x screws through the base ears into the desk.
// Fits a Raspberry Pi 5 with the official Active Cooler. Sizes in mm.

part = "assembly";   // "head", "sled" or "assembly" (preview)
$fn = 48;

// ---- Raspberry Pi 5 ---------------------------------------------------
pcb_x = 85; pcb_y = 56; pcb_t = 1.6;
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];

// ---- overall ------------------------------------------------------------
base_t   = 3;
sled_t   = 3;
standoff = 5;
above    = 24;                   // cooler + USB stack
mouth_w  = pcb_y + 6;            // tunnel width
mouth_h  = sled_t + standoff + pcb_t + above + 2;
mouth_ch = 10;                   // 45 degree corners at the top (short bridge)

fin_t    = 2.2;                  // fin thickness (5-6 perimeters)
fin_gap  = 3.8;                  // air gap: too narrow for fingers
n_fins   = 16;
pitch    = fin_t + fin_gap;
head_len = (n_fins - 1) * pitch + fin_t;   // about 93 mm, front to back
back_ext = 26;                   // base plate behind the head: cables + sled screws
front_ext = 6;

smear_amp = 30;                  // how far the skull drifts sideways, front to back
pcb_z = base_t + sled_t + standoff;          // underside of the board

// ---- the head, one frontal slice -----------------------------------------
// t = 0 is the face, t = 1 the back of the skull
function depth_scale(t) = 0.80 + 0.20 * pow(sin(180 * min(1, t * 1.15)), 0.6);
function smear(t)       = smear_amp * (sin(230 * t - 40) + 0.4 * sin(610 * t + 30));
function lift(t)        = 9 * sin(410 * t + 60);           // skull bobs up and down
function tilt(t)        = 18 * sin(300 * t + 10);          // and twists

module silhouette(t) {
    s = depth_scale(t);
    d = smear(t);
    scale([s, 0.88 + 0.12 * s]) hull() {
        translate([0.25 * d, 30]) scale([50, 34]) circle(1);     // jaw
        translate([d, 92 + lift(t)]) rotate(tilt(t)) scale([52, 44]) circle(1);   // skull
        translate([0.6 * d, 70 + 0.5 * lift(t)]) rotate(-tilt(t)) scale([40, 14]) circle(1); // cheekbones
        translate([-22 + 0.15 * d, 0]) square([44, 6]);          // neck
    }
}

module mouth2d() {
    // the scream: a squared-off opening with 45 degree shoulders
    polygon([[-mouth_w / 2, -1], [mouth_w / 2, -1],
             [mouth_w / 2, mouth_h - mouth_ch], [mouth_w / 2 - mouth_ch, mouth_h],
             [-mouth_w / 2 + mouth_ch, mouth_h], [-mouth_w / 2, mouth_h - mouth_ch]]);
}

module fin(i) {
    t = i / (n_fins - 1);
    x = i * pitch;
    translate([x, 0, base_t]) rotate([90, 0, 90])
    linear_extrude(fin_t) difference() {
        silhouette(t);
        translate([0, 0]) mouth2d();
        // side window for USB-C and both micro-HDMI (board x 2..52)
        if (x >= front_ext * 0 + 2 && x <= 54)
            translate([-mouth_w / 2 - 60, -1]) square([62, pcb_z - base_t + pcb_t + 10]);
        // eye: a single hole that drifts with the skull, only in the first fins
        if (i < 6) translate([smear(t) * depth_scale(t) + 18, 98 + lift(t)]) rotate(tilt(t)) scale([8, 4]) circle(1);
    }
}

module tie_rods() {
    // horizontal rods through the skull hold the fins together;
    // between fins they are 3 mm bridges, fine without supports
    for (p = [[0, 80], [0, 104], [-18, 58], [18, 58]])
        translate([0, p[0], base_t + p[1]]) rotate([0, 90, 0]) cylinder(d = 5, h = head_len);
}

module base_plate() {
    difference() {
        translate([-front_ext, -60, 0])
            linear_extrude(base_t) offset(5) offset(-5)
                square([front_ext + head_len + back_ext, 120]);
        // sled screw holes (M3 pilot) behind the head
        for (y = [-18, 18]) translate([head_len + 12, y, -1]) cylinder(d = 2.6, h = base_t + 2);
        // desk screw ears, countersunk
        for (p = [[-front_ext + 9, -48], [-front_ext + 9, 48], [head_len + back_ext - 9, -48], [head_len + back_ext - 9, 48]])
            translate([p[0], p[1], -1]) {
                cylinder(d = 4.5, h = base_t + 2);
                translate([0, 0, base_t + 1 - 2.5]) cylinder(d1 = 4.5, d2 = 9, h = 2.5);
            }
        // zip-tie slots for the cables leaving the back of the head
        for (y = [-34, -10, 14]) translate([head_len + 18, y, -1]) cube([3, 20, base_t + 2]);
        // words on the underside, mirrored to read from below
        translate([head_len / 2, 0, -0.01]) mirror([1, 0, 0]) linear_extrude(0.8) {
            translate([0, 6])  text("DARK DATA", size = 8, font = "Liberation Sans:style=Bold", halign = "center");
            translate([0, -8]) text("CUSTOM MADE INTIMACY", size = 4.5, font = "Liberation Sans:style=Bold", halign = "center");
        }
    }
    // INFINITE JEST, upside down, raised on the plate behind the head
    translate([head_len + back_ext - 5, 40, base_t - 0.01]) rotate(90 + 180)
        linear_extrude(1) text("INFINITE JEST", size = 5, font = "Liberation Sans:style=Bold");
}

module head() {
    base_plate();
    for (i = [0 : n_fins - 1]) fin(i);
    tie_rods();
}

// ---- sled -----------------------------------------------------------------
sled_w = mouth_w - 1.2;
sled_l = head_len + 20;
pcb_off_x = 2;                    // board starts 2 mm behind the face

module sled() {
    difference() {
        union() {
            translate([0, -sled_w / 2, 0]) cube([sled_l, sled_w, sled_t]);
            for (h = holes) translate([pcb_off_x + h[0], -pcb_y / 2 + h[1], 0])
                cylinder(d = 6, h = sled_t + standoff);
            // finger pull at the back
            translate([sled_l - 4, -14, 0]) cube([4, 28, 12]);
        }
        for (h = holes) translate([pcb_off_x + h[0], -pcb_y / 2 + h[1], 1])
            cylinder(d = 2.2, h = sled_t + standoff);
        // screws into the base plate
        for (y = [-18, 18]) translate([head_len + 12, y, -1]) {
            cylinder(d = 3.4, h = sled_t + 2);
            translate([0, 0, sled_t + 1 - 1.8]) cylinder(d1 = 3.4, d2 = 6.4, h = 1.8);
        }
        // air slots under the board
        for (x = [12 : 9 : 75]) translate([x, -18, -1]) cube([4, 36, sled_t + 2]);
        translate([sled_l - 2, 0, 6]) rotate([0, 90, 0]) linear_extrude(3)
            text("J R A", size = 5, font = "Liberation Sans:style=Bold", halign = "center", valign = "center");
    }
}

// ---------------------------------------------------------------------------
if (part == "head") head();
else if (part == "sled") sled();
else {
    color("#2a2626") head();
    color("#d9826b") translate([0, 0, base_t]) sled();
    color("#4a7a4a") translate([pcb_off_x, -pcb_y / 2, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
}
