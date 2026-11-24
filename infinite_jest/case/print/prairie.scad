// INFINITE JEST · "Prairie" · Raspberry Pi 5 case, after Frank Lloyd Wright
// ---------------------------------------------------------------------------
// Wright pressed his houses flat against the ground: long horizontal bands,
// roofs that cantilever far past the walls, one vertical masonry chimney to
// anchor it all, and geometric art-glass in the windows. Here the walls are
// stacked horizontal louvers (the gaps are the ventilation), a terrace slab
// cantilevers out on two sides like Fallingwater's balconies, a ribbed stone
// chimney rises through the roof, and the fan breathes through an art-glass
// pattern cut into a deep, double roof.
//
// Two parts, both print with no supports:
//   part = "base";   // plinth, louvered walls, terrace, chimney, standoffs
//   part = "roof";   // two stacked roof planes, prints the right way up
//
//   openscad -D 'part="base"' -o prairie_base.stl prairie.scad
//   openscad -D 'part="roof"' -o prairie_roof.stl prairie.scad
//
// Access (Raspberry Pi 5 with the official Active Cooler):
//   microSD end : power button, status LEDs, microSD card
//   long side   : USB-C power, micro-HDMI 0 and 1
//   short end   : 4x USB, Ethernet
//   roof        : 4 countersunk M3 x 10 screws; lift for GPIO and fan
// Hardware: 4x M2.5 heat-set inserts (4 mm long) + 4x M2.5 x 6 mm screws (Pi),
//           4x M3 heat-set inserts (5 mm long) + 4x M3 x 10 mm countersunk (roof),
//           4x 8 mm rubber bumpers. Set threads = "self" for plain
//           self-tapping screws instead. Sizes in mm.
// Board coordinates: x = 0 is the microSD end, y = 0 the HDMI edge.

part = "assembly";   // "base", "roof", "assembly"
$fn = 40;

// ---- Raspberry Pi 5 -------------------------------------------------------
pcb_x = 85; pcb_y = 56; pcb_t = 1.6;
holes = [[3.5, 3.5], [61.5, 3.5], [3.5, 52.5], [61.5, 52.5]];

// ---- levels ---------------------------------------------------------------
plinth_h = 3; podium_t = 3; standoff = 5; clear_top = 19;
wall = 2.4; gap = 1; shadow = 3.5;     // 2.4 mm walls = 6 perimeters with a 0.4 nozzle
podium_z = plinth_h + podium_t;
pcb_z = podium_z + standoff;
top_z = pcb_z + pcb_t;
wall_z = top_z + clear_top;
roof_z = wall_z + shadow;
roof1_t = 3.5; roof2_t = 3;

// threads: "self" = self-tapping screws straight into plastic,
//          "insert" = brass heat-set inserts (stronger, survives many openings)
threads = "insert";
m25_hole = threads == "insert" ? 3.6 : 2.2;   // M2.5 x 4 mm insert, 3.5 mm OD
m3_hole  = threads == "insert" ? 4.0 : 2.6;   // M3 x 5 mm insert, 4.0 mm OD

wx0 = -gap - wall; wx1 = pcb_x + gap + wall;
wy0 = -gap - wall; wy1 = pcb_y + gap + wall;

// plinth: long and low, reaching past the walls at both ends
px0 = wx0 - 10; px1 = wx1 + 14; py0 = wy0 - 9; py1 = wy1 + 16;

// louvers
louver_pitch = 4; louver_gap = 1.8;
pier = 5;                                   // solid piers between louver bays
bay = 17;                                   // bay width: louver bridges stay at 12 mm

// openings (same as the Pavilion: they fit the board)
open_ports = [[-2.5, pcb_y + 2.5], [top_z - 1.2, top_z + 17.6]];
open_side  = [[2, 53.5], [top_z - 1.6, top_z + 9]];
open_front = [[3.5, 42.5], [podium_z + 2.2, top_z + 7.5]];   // starts above the inner fillet

// terrace: an L-shaped cantilever round the microSD end and the GPIO side
terrace_z = top_z + 8.5; terrace_t = 3; terrace_out = 8;

// chimney on the GPIO side, outside the wall
ch_x0 = 30; ch_w = 16; ch_d = 11; ch_top = roof_z + roof1_t + roof2_t + 10;

// roof planes
ov = 11;
r1 = [wx0 - ov, wy0 - ov, wx1 + ov, wy1 + ov];            // lower, wide
r2 = [44, wy0 - ov + 5, wx1 + ov, wy1 + ov - 5];          // upper, a second plane over the port end

pier_s = 8;
roof_screws = [for (x = [wx0 - 2, wx1 + 2], y = [wy0 - 2, wy1 + 2]) [x, y]];

module rect(x0, y0, x1, y1, h) { translate([x0, y0, 0]) cube([x1 - x0, y1 - y0, h]); }

// horizontal louver slots along a wall (positions a..b along it), skipping piers
module louvers(a, b, z0, z1, d = 4.5) {
    nb = floor((b - a) / bay);
    s = a + ((b - a) - nb * bay) / 2;
    for (i = [0 : nb - 1], z = [z0 : louver_pitch : z1 - louver_gap])
        translate([s + i * bay + pier / 2, 0, z]) cube([bay - pier, d, louver_gap]);
}

module podium() {
    hull() {
        rect(px0 + plinth_h, py0 + plinth_h, px1 - plinth_h, py1 - plinth_h, 0.01);
        translate([0, 0, plinth_h - 0.01]) rect(px0, py0, px1, py1, 0.01);
    }
    translate([0, 0, plinth_h]) rect(px0, py0, px1, py1, podium_t);
}

module terrace() {
    // cantilever slab with a 45 degree underside, so it prints without support
    module slab(x0, y0, x1, y1) hull() {
        translate([0, 0, terrace_z]) rect(x0, y0, x1, y1, terrace_t);
        translate([0, 0, terrace_z - terrace_out]) rect(x0 + (x0 < wx0 ? terrace_out : 0), y0, x1, y1 - (y1 > wy1 ? terrace_out : 0), 0.01);
    }
    slab(wx0 - terrace_out, wy0 + 10, wx0 + 0.01, wy1 + terrace_out);    // microSD end
    slab(wx0 - terrace_out, wy1 - 0.01, ch_x0, wy1 + terrace_out);       // GPIO side, up to the chimney
}

module chimney() {
    difference() {
        rect(ch_x0, wy1 - 0.01, ch_x0 + ch_w, wy1 + ch_d, ch_top);
        // stone coursing: horizontal joints, long and short, staggered
        for (k = [0 : floor(ch_top / 3.2)]) {
            z = 1.6 + k * 3.2;
            for (side = [0, 1]) {
                xo = (k % 2) * 4;
                // front face
                translate([ch_x0 - 1, wy1 + ch_d - 0.6, z]) cube([ch_w + 2, 1, 0.7]);
                // vertical joints, staggered every other course
                translate([ch_x0 + 5 + xo, wy1 + ch_d - 0.6, z - 2.5]) cube([0.7, 1, 2.5]);
            }
            translate([ch_x0 - 0.4, wy1, z]) cube([1, ch_d + 1, 0.7]);
            translate([ch_x0 + ch_w - 0.6, wy1, z]) cube([1, ch_d + 1, 0.7]);
        }
        // flue: the chimney also breathes, open at the top into the case
        translate([ch_x0 + 4, wy1 - 1, wall_z - 4]) cube([ch_w - 8, 4, 4]);
        translate([ch_x0 + 4, wy1 + 1.5, wall_z - 4]) cube([ch_w - 8, ch_d - 4, ch_top]);
    }
}

module walls() {
    lz0 = podium_z + 2.5; lz1 = wall_z - 2;
    difference() {
        difference() {
            rect(wx0, wy0, wx1, wy1, wall_z);
            translate([0, 0, -1]) rect(wx0 + wall, wy0 + wall, wx1 - wall, wy1 - wall, wall_z + 2);
        }
        translate([0, wy0 - 2, 0]) louvers(wx0 + 2, wx1 - 2, lz0, lz1);                               // HDMI side
        translate([0, wy1 - 2.5, 0]) louvers(wx0 + 2, ch_x0 - 1, lz0, lz1);                              // GPIO side, left of chimney
        translate([0, wy1 - 2.5, 0]) louvers(ch_x0 + ch_w + 1, wx1 - 2, lz0, lz1);                      // right of chimney
        translate([wx0 + 2.5, 0, 0]) rotate([0, 0, 90]) louvers(wy0 + 2, wy1 - 2, lz0, lz1);             // microSD end
        // port openings
        translate([0, 0, open_ports[1][0]]) rect(wx1 - wall - 1, open_ports[0][0], wx1 + 5, open_ports[0][1], open_ports[1][1] - open_ports[1][0]);
        translate([0, 0, open_side[1][0]])  rect(open_side[0][0], wy0 - 5, open_side[0][1], wy0 + wall + 1, open_side[1][1] - open_side[1][0]);
        translate([0, 0, open_front[1][0]]) rect(wx0 - 5, open_front[0][0], wx0 + wall + 1, open_front[0][1], open_front[1][1] - open_front[1][0]);
    }
        // corner piers outside the walls carry the roof across the shadow gap
    // (outside, so they never touch the board's corners)
    for (c = roof_screws) translate([c[0] - pier_s / 2, c[1] - pier_s / 2, 0]) cube([pier_s, pier_s, roof_z]);
    // 45 degree fillet where the walls meet the podium, inside: stiffer walls, no supports
    difference() {
        hull() {
            translate([0, 0, podium_z - 0.01]) rect(wx0 + wall, wy0 + wall, wx1 - wall, wy1 - wall, 0.01);
            translate([0, 0, podium_z + 2]) rect(wx0 + wall, wy0 + wall, wx1 - wall, wy1 - wall, 0.01);
        }
        hull() {
            translate([0, 0, podium_z - 0.02]) rect(wx0 + wall + 2, wy0 + wall + 2, wx1 - wall - 2, wy1 - wall - 2, 0.01);
            translate([0, 0, podium_z + 2.01]) rect(wx0 + wall, wy0 + wall, wx1 - wall, wy1 - wall, 0.01);
        }
    }
}



module base() {
    difference() {
        union() {
            podium();
            walls();
            terrace();
            chimney();
            for (h = holes) translate([h[0], h[1], podium_z - 0.01]) {
                cylinder(d = 7, h = standoff + 0.01);
                cylinder(d1 = 11, d2 = 7, h = 2);          // gusseted foot
            }
        }
        for (h = holes) translate([h[0], h[1], podium_z - 1]) cylinder(d = m25_hole, h = standoff + 3);
        for (s = roof_screws) translate([s[0], s[1], roof_z - 10]) cylinder(d = m3_hole, h = 11, $fn = 24);
        // labels engraved in the podium in front of each opening
        lbl_t = 0.6;
        translate([wx0 - 6.5, (open_front[0][0] + open_front[0][1]) / 2, podium_z - lbl_t]) rotate(90) linear_extrude(1)
            text("POWER  \u00b7  microSD", size = 2.8, font = "Liberation Sans:style=Bold", halign = "center", valign = "center");
        translate([(open_side[0][0] + open_side[0][1]) / 2, wy0 - 2.6, podium_z - lbl_t]) linear_extrude(1)
            text("USB-C   HDMI 0   HDMI 1", size = 2.8, font = "Liberation Sans:style=Bold", halign = "center", valign = "center");
        translate([wx1 + 11, pcb_y / 2, podium_z - lbl_t]) rotate(-90) linear_extrude(1)
            text("USB   \u00b7   ETHERNET", size = 2.8, font = "Liberation Sans:style=Bold", halign = "center", valign = "center");
        // air in through the floor, under the board
        for (x = [12 : 5 : 72]) translate([x, 10, -1]) cube([2.2, 36, podium_z + 2]);
        // the port openings continue through the terrace where they meet it
        translate([0, 0, open_front[1][0]]) rect(wx0 - terrace_out - 1, open_front[0][0], wx0 + wall + 1, open_front[0][1], open_front[1][1] - open_front[1][0]);
        // zip-tie slots on the plinth at the port end and the HDMI side
        for (y = [4, 22, 40]) translate([wx1 + 5, y, -1]) cube([2.4, 9, podium_z + 2]);
        for (x = [10, 30, 50]) translate([x, py0 + 1.6, -1]) cube([9, 2.4, podium_z + 2]);
        // bumper seats
        for (x = [px0 + 12, px1 - 12], y = [py0 + 12, py1 - 12]) translate([x, y, -0.01]) cylinder(d = 8.6, h = 0.8);
    }
}

module frame(w, h, t, c) {
    translate([c, 0]) square([w - 2 * c, t]);
    translate([c, h - t]) square([w - 2 * c, t]);
    translate([0, c]) square([t, h - 2 * c]);
    translate([w - t, c]) square([t, h - 2 * c]);
}

// art glass: a Wright-style geometric grille over the fan
module art_glass(cx, cy) {
    w = 40; h = 30; t = 1.6;
    translate([cx - w / 2, cy - h / 2]) {
        // frame lines, broken at the corners so nothing falls out
        frame(w, h, t, 3);
        // tall verticals, grouped in threes like a Prairie window
        for (x = [9, 12, 15, w - 15 - t, w - 12 - t, w - 9 - t]) translate([x, t + 4]) square([t, h - 2 * t - 8]);
        // a central square and the cross-bar through it
        translate([w / 2 - 5, h / 2 - 5]) frame(10, 10, t, 2.2);
        translate([4, h / 2 - t / 2]) square([w / 2 - 9, t]);
        translate([w / 2 + 5, h / 2 - t / 2]) square([w / 2 - 9, t]);
        // small squares in the corners
        for (p = [[4, 4], [w - 8, 4], [4, h - 8], [w - 8, h - 8]]) translate(p) square(4);
    }
}

module roof() {
    difference() {
        union() {
            translate([0, 0, roof_z]) rect(r1[0], r1[1], r1[2], r1[3], roof1_t);
            translate([0, 0, roof_z + roof1_t - 0.01]) rect(r2[0], r2[1], r2[2], r2[3], roof2_t);
        }
        // the chimney passes through
        translate([0, 0, roof_z - 1]) rect(ch_x0 - 0.6, wy1 - 0.6, ch_x0 + ch_w + 0.6, wy1 + ch_d + 0.6, 20);
        // the fan breathes through the art glass
        translate([0, 0, roof_z - 1]) linear_extrude(roof1_t + roof2_t + 2) art_glass(26, 28);
        for (s = roof_screws) translate([s[0], s[1], roof_z - 1]) {
            cylinder(d = 3.4, h = 20, $fn = 20);
            z_top = (s[0] > r2[0]) ? roof1_t + roof2_t : roof1_t;
            translate([0, 0, z_top + 1 - 1.9]) cylinder(d1 = 3.4, d2 = 6.6, h = 1.91, $fn = 24);
        }
    }
}

// ---------------------------------------------------------------------------
if (part == "fitcheck")   // must come out empty: the board and its keep-out vs the base
    intersection() { base(); translate([-0.5, -0.5, pcb_z]) cube([pcb_x + 1, pcb_y + 1, pcb_t + 0.01]); }
else if (part == "base") base();
else if (part == "roof") translate([0, 0, -roof_z]) roof();
else {
    color("#c9b8a0") base();          // warm Wright brick-and-sand
    color("#7a3b2a") roof();          // Cherokee red
    color("#4a7a4a") translate([0, 0, pcb_z]) cube([pcb_x, pcb_y, pcb_t]);
    color("#2b2b2b") translate([18, 12, top_z]) cube([42, 34, 13]);
    color("#b8b8b8") translate([pcb_x - 18, 2, top_z]) cube([21, 52, 16]);
}
