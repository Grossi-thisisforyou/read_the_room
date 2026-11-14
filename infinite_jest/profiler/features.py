"""Turn raw sensor messages into a small set of behavioural features.

Everything here is a rolling summary held in memory for one visit. No frames,
no audio, no coordinates history is kept beyond short windows; the summary is
dropped on reset().

Each feature ends up as a number in roughly [-1, 1] ("lower than a typical
visitor" .. "higher than a typical visitor") plus an amount of evidence in
[0, 1] that says how much data it rests on. The "typical visitor" norms are
guesses to tune at the mini showing (see NORMS).
"""

import math
from collections import deque

# Rough norms for a gallery visitor seen by a phone camera. Tune these at the
# mini showing: watch 5 people, read the debug output, adjust centre/spread.
NORMS = {
    # name: (centre, spread)
    "pace": (0.12, 0.10),         # cx units per second while walking in
    "closeness": (0.35, 0.20),    # max size (box height / frame height)
    "approach_time": (12.0, 8.0), # seconds until first got close
    "motion": (0.25, 0.15),       # mean motion energy while present
    "burstiness": (0.6, 0.35),    # coefficient of variation of motion
    "roaming": (0.35, 0.20),      # range of horizontal positions visited
    "gaze": (0.45, 0.25),         # fraction of time a frontal face is seen
    "voice": (0.10, 0.12),        # fraction of time speech is heard
    "loudness": (0.25, 0.15),     # mean audio level while voiced
    "touch_rate": (4.0, 4.0),     # touches per minute
    "touch_variety": (0.4, 0.25), # spread of touch positions + gesture types
    "hold_ratio": (0.2, 0.2),     # fraction of touches that are long holds
    "choice_speed": (2.5, 1.5),   # seconds to answer a prompt (inverted)
    "shake": (0.15, 0.15),        # mean accel deviation from 1 g
    "dwell": (40.0, 25.0),        # seconds present so far
    "typing": (12.0, 15.0),       # characters typed on the slide keyboard
    "handled": (0.25, 0.25),      # fraction of the visit holding the phone
    "tilt_range": (60.0, 40.0),   # degrees of beta+gamma explored while held
    "tilt_speed": (40.0, 30.0),   # mean degrees per second of turning
}


def num(x, default=0.0):
    """float(x) for junk input: None, dicts, strings, NaN and inf give default."""
    if isinstance(x, bool):
        return 1.0 if x else 0.0
    try:
        v = float(x)
    except (TypeError, ValueError, OverflowError):
        return default
    return v if math.isfinite(v) else default


def clamp(x, lo=-1.0, hi=1.0):
    return max(lo, min(hi, x))


def z(name, value):
    centre, spread = NORMS[name]
    return clamp((value - centre) / spread / 2.0)


def saturate(n, half):
    """Evidence curve: 0 at n=0, 0.5 at n=half, approaching 1."""
    return 1.0 - math.exp(-n * math.log(2) / half) if n > 0 else 0.0


# In handheld mode the camera is in the visitor's hand: walking pace, roaming
# and approach are meaningless, and "closeness" becomes how close they hold
# the phone to their face.
HANDHELD_DROP = ("pace", "roaming", "approach_time", "handled")  # everyone holds it


class Features:
    def __init__(self, mode="handheld"):
        self.mode = mode
        self.reset()

    def reset(self):
        self.t0 = None
        self.t_last = None
        self.present_time = 0.0
        self.vision_n = 0
        self.prev_cx = None
        self.prev_t = None
        self.pace_samples = deque(maxlen=40)
        self.max_size = 0.0
        self.t_close = None
        self.motion_sum = 0.0
        self.motion_sq = 0.0
        self.motion_n = 0
        self.recent_motion = deque(maxlen=20)
        self.recent_size = deque(maxlen=20)
        self.recent_face = deque(maxlen=20)
        self.cx_min = None
        self.cx_max = None
        self.face_n = 0
        self.audio_n = 0
        self.voiced_sum = 0.0
        self.loud_sum = 0.0
        self.loud_w = 0.0
        self.recent_voice = deque(maxlen=20)
        self.touches = []  # (t, gesture, x, y, duration_ms), capped
        self.recent_touch_t = deque(maxlen=20)
        self.choices = []  # (prompt_id, option, latency_ms)
        self.accel_n = 0
        self.shake_sum = 0.0
        self.prox_near_since = None
        self.keys_chars = 0
        self.phone_n = 0
        self.held_n = 0
        self.recent_held_t = None
        self.recent_tilt_speed = deque(maxlen=20)
        self.recent_shake = deque(maxlen=20)
        self.tilt_min = [999.0, 999.0]
        self.tilt_max = [-999.0, -999.0]
        self.prev_tilt = None
        self.tilt_speed_sum = 0.0
        self.tilt_speed_n = 0
        self.face_seen_n = 0
        self.touch_down = None
        self.last_vision_ts = None
        self.keys_events = 0

    # ------------------------------------------------------------------ input
    def add(self, data, ts):
        kind = data.get("kind")
        if self.t0 is None:
            self.t0 = ts
        if self.t_last is not None and ts > self.t_last:
            dt = min(ts - self.t_last, 2.0)
        else:
            dt = 0.0
        self.t_last = ts
        handler = getattr(self, "_on_" + str(kind), None)
        if handler:
            handler(data, ts, dt)

    def _on_vision(self, d, ts, dt, fallback=False):
        if not fallback:
            self.last_vision_ts = ts
        if not d.get("present", True):
            self.prev_cx = None
            return
        self.present_time += dt
        motion = num(d.get("motion"))
        self.motion_sum += motion
        self.motion_sq += motion * motion
        self.motion_n += 1
        self.recent_motion.append(motion)
        if d.get("cx") is None:  # phone fallback: presence and motion only
            return
        self.vision_n += 1
        cx = clamp(num(d.get("cx", 0.5), 0.5), 0.0, 1.0)
        size = clamp(num(d.get("size")), 0.0, 1.0)
        face = d.get("face")
        if face is not None:
            self.face_seen_n += 1
            self.recent_face.append(1.0 if face else 0.0)
        elapsed = ts - self.t0
        # Pace: horizontal speed in the first 15 s (walking in).
        if self.prev_cx is not None and ts > self.prev_t and elapsed < 15:
            self.pace_samples.append(abs(cx - self.prev_cx) / (ts - self.prev_t))
        self.prev_cx, self.prev_t = cx, ts
        if size > self.max_size:
            self.max_size = size
        if self.t_close is None and size >= NORMS["closeness"][0]:
            self.t_close = elapsed
        self.recent_size.append(size)
        self.cx_min = cx if self.cx_min is None else min(self.cx_min, cx)
        self.cx_max = cx if self.cx_max is None else max(self.cx_max, cx)
        if face:
            self.face_n += 1

    def _on_audio(self, d, ts, dt):
        self.audio_n += 1
        level = num(d.get("level", 0.0))
        voiced = num(d.get("voiced", 0.0))
        self.voiced_sum += voiced
        self.loud_sum += level * voiced
        self.loud_w += voiced
        self.recent_voice.append(voiced)

    def _on_touch(self, d, ts, dt):
        # Contract shape: {x, y, down}. A down/up pair becomes one touch with
        # a duration; {gesture, duration_ms} events are accepted as well.
        x, y = num(d.get("x", 0.5)), num(d.get("y", 0.5))
        if "down" in d and "gesture" not in d:
            if d["down"]:
                self.touch_down = (ts, x, y)
                return
            if self.touch_down is None:
                return
            t0, x0, y0 = self.touch_down
            self.touch_down = None
            dur = (ts - t0) * 1000.0
            moved = abs(x - x0) + abs(y - y0)
            gesture = "swipe" if moved > 0.15 else ("hold" if dur > 800 else "tap")
            x, y = x0, y0
        else:
            gesture = d.get("gesture", "tap")
            dur = num(d.get("duration_ms", 100))
        if len(self.touches) < 200:
            self.touches.append((ts, gesture, x, y, dur))
        self.recent_touch_t.append(ts)

    def _on_choice(self, d, ts, dt):
        if len(self.choices) < 50:
            lat = d.get("latency_ms")
            self.choices.append((str(d.get("prompt_id"))[:40], str(d.get("option"))[:40],
                                 num(lat, None)))

    def _on_accel(self, d, ts, dt):
        x, y, zz = (num(d.get(k, 0.0)) for k in ("x", "y", "z"))
        mag = math.sqrt(x * x + y * y + zz * zz)
        self.accel_n += 1
        self.shake_sum += abs(mag - 1.0)
        self.recent_shake.append(abs(mag - 1.0))

    def _on_phone(self, d, ts, dt):
        """The N900's bundled ~10 Hz packet: unpack the parts we use."""
        # If no camera frames are arriving, fall back to the phone's own
        # presence/motion estimate (no position or distance then).
        if (self.last_vision_ts is None or ts - self.last_vision_ts > 2.0) and "presence" in d:
            self._on_vision({"present": num(d.get("presence")) > 0.5,
                             "motion": num(d.get("motion")),
                             "cx": None, "size": None, "face": None}, ts, dt, fallback=True)
        if isinstance(d.get("audio"), dict):
            self._on_audio(d["audio"], ts, dt)
        held = bool(d.get("held")) and d.get("held") not in (0, "0")
        if "held" in d:
            self.phone_n += 1
            if held:
                self.held_n += 1
                self.recent_held_t = ts
        if isinstance(d.get("accel"), dict) and held:
            self._on_accel(d["accel"], ts, dt)
        tilt = d.get("tilt")
        if held and isinstance(tilt, dict):
            b, g = num(tilt.get("beta") or 0.0), num(tilt.get("gamma") or 0.0)
            self.tilt_min = [min(self.tilt_min[0], b), min(self.tilt_min[1], g)]
            self.tilt_max = [max(self.tilt_max[0], b), max(self.tilt_max[1], g)]
            if self.prev_tilt is not None and 0 < ts - self.prev_tilt[2] < 2.0:
                sp = (abs(b - self.prev_tilt[0]) + abs(g - self.prev_tilt[1])) / (ts - self.prev_tilt[2])
                self.tilt_speed_sum += sp
                self.tilt_speed_n += 1
                self.recent_tilt_speed.append(sp)
            self.prev_tilt = (b, g, ts)
        elif not held:
            self.prev_tilt = None
        if isinstance(d.get("proximity"), dict):
            self._on_proximity(d["proximity"], ts, dt)

    def _on_keys(self, d, ts, dt):
        # Only the amount typed is kept, never the text itself.
        self.keys_chars += len(str(d.get("text", "")))
        self.keys_events += 1

    def _on_proximity(self, d, ts, dt):
        if d.get("near"):
            if self.prox_near_since is None:
                self.prox_near_since = ts
        else:
            self.prox_near_since = None

    # ----------------------------------------------------------------- output
    def covered_for(self, ts):
        """Seconds the proximity sensor has been covered (opt-out gesture)."""
        return 0.0 if self.prox_near_since is None else ts - self.prox_near_since

    def elapsed(self):
        return 0.0 if self.t0 is None else self.t_last - self.t0

    def summary(self):
        """Return {feature: (value in [-1,1], evidence in [0,1], raw)}."""
        out = self._summary()
        if self.mode == "handheld":
            for k in HANDHELD_DROP:
                out.pop(k, None)
        return out

    def _summary(self):
        out = {}
        if len(self.pace_samples) >= 3:
            raw = sum(self.pace_samples) / len(self.pace_samples)
            out["pace"] = (z("pace", raw), saturate(len(self.pace_samples), 10), raw)
        if self.motion_n >= 3:
            mean = self.motion_sum / self.motion_n
            out["motion"] = (z("motion", mean), saturate(self.motion_n, 25), mean)
            var = max(0.0, self.motion_sq / self.motion_n - mean * mean)
            cv = math.sqrt(var) / mean if mean > 1e-3 else 0.0
            out["burstiness"] = (z("burstiness", cv), saturate(self.motion_n, 50), cv)
            out["dwell"] = (z("dwell", self.present_time),
                            saturate(self.present_time, 20), self.present_time)
        if self.vision_n >= 3:
            out["closeness"] = (z("closeness", self.max_size),
                                saturate(self.vision_n, 30), self.max_size)
            el = self.elapsed()
            if self.t_close is not None:
                raw = self.t_close
                out["approach_time"] = (-z("approach_time", raw), saturate(el, 15), raw)
            elif el > 20:
                out["approach_time"] = (-1.0, saturate(el - 20, 15), el)
            rng = self.cx_max - self.cx_min
            out["roaming"] = (z("roaming", rng), saturate(self.vision_n, 40), rng)
        if self.face_seen_n >= 3:
            g = self.face_n / self.face_seen_n
            out["gaze"] = (z("gaze", g), saturate(self.face_seen_n, 25), g)
        if self.audio_n >= 3:
            v = self.voiced_sum / self.audio_n
            out["voice"] = (z("voice", v), saturate(self.audio_n, 30), v)
            if self.loud_w > 1.0:
                ld = self.loud_sum / self.loud_w
                out["loudness"] = (z("loudness", ld), saturate(self.loud_w, 10), ld)
        el = self.elapsed()
        if el > 10 and (self.touches or el > 30):
            rate = len(self.touches) / (el / 60.0)
            out["touch_rate"] = (z("touch_rate", rate), saturate(el, 30), rate)
        if len(self.touches) >= 3:
            xs = [t[2] for t in self.touches]
            ys = [t[3] for t in self.touches]
            kinds = len(set(t[1] for t in self.touches))
            spread = (max(xs) - min(xs) + max(ys) - min(ys)) / 2.0
            variety = 0.7 * spread + 0.3 * (kinds - 1) / 2.0
            out["touch_variety"] = (z("touch_variety", variety),
                                    saturate(len(self.touches), 6), variety)
            holds = sum(1 for t in self.touches
                        if t[1] == "hold" or t[4] > 800) / len(self.touches)
            out["hold_ratio"] = (z("hold_ratio", holds), saturate(len(self.touches), 6), holds)
        lats = [c[2] for c in self.choices if c[2] is not None]
        if lats:
            lat = sum(lats) / len(lats) / 1000.0
            out["choice_speed"] = (-z("choice_speed", lat), saturate(len(lats), 2), lat)
        if self.keys_events:
            out["typing"] = (z("typing", self.keys_chars),
                             saturate(self.keys_events, 2), self.keys_chars)
        if self.phone_n >= 20:
            h = self.held_n / self.phone_n
            out["handled"] = (z("handled", h), saturate(self.phone_n, 60), h)
        if self.held_n >= 10 and self.tilt_max[0] > -999:
            rng = (self.tilt_max[0] - self.tilt_min[0]) + (self.tilt_max[1] - self.tilt_min[1])
            out["tilt_range"] = (z("tilt_range", rng), saturate(self.held_n, 40), rng)
        if self.tilt_speed_n >= 10:
            sp = self.tilt_speed_sum / self.tilt_speed_n
            out["tilt_speed"] = (z("tilt_speed", sp), saturate(self.tilt_speed_n, 40), sp)
        if self.accel_n >= 5:
            s = self.shake_sum / self.accel_n
            out["shake"] = (z("shake", s), saturate(self.accel_n, 30), s)
        return out

    def _engagement_handheld(self):
        """Handheld: a visitor who is held by a scene steadies the phone,
        turns it less, stops shaking it and brings it closer. Each part is
        compared with this visitor's own average so far, so calm and restless
        people both give the bandit a contrast to learn from."""
        def mean(q):
            return sum(q) / len(q) if q else 0.0
        rel = lambda now, base: clamp(now / (2.0 * base + 1e-6), 0.0, 1.0)
        base_tilt = self.tilt_speed_sum / max(1, self.tilt_speed_n)
        steady = 1.0 - rel(mean(self.recent_tilt_speed), base_tilt)
        base_shake = self.shake_sum / max(1, self.accel_n)
        calm = 1.0 - rel(mean(self.recent_shake), base_shake) if self.recent_shake else 0.5
        base_mot = self.motion_sum / max(1, self.motion_n)
        still = 1.0 - rel(mean(self.recent_motion), base_mot) if self.recent_motion else 0.5
        near = clamp(mean(self.recent_size) / 0.6, 0.0, 1.0) if self.recent_size else 0.5
        look = mean(self.recent_face) if self.recent_face else 0.5
        voice = min(1.0, mean(self.recent_voice) * 3) if self.recent_voice else 0.0
        score = (0.35 * steady + 0.15 * calm + 0.20 * still + 0.15 * near
                 + 0.10 * look + 0.05 * voice)
        if self.recent_held_t is None or self.t_last - self.recent_held_t > 2:
            score *= 0.3  # put down
        return clamp(score, 0.0, 1.0)

    def engagement(self):
        """How held is the visitor right now, 0..1, from the recent window.

        Held = present, close or getting closer, looking, still-but-there or
        touching/speaking. Gone = 0. This is the reward the hook bandit uses.
        """
        if self.mode == "handheld" and self.recent_tilt_speed:
            return self._engagement_handheld()
        if not self.recent_size and not self.recent_motion:
            return 0.0
        size = list(self.recent_size) or [0.3]
        n = len(size)
        near = sum(size) / n
        trend = size[-1] - size[0]
        look = (sum(self.recent_face) / len(self.recent_face)) if self.recent_face else 0.5
        mot = sum(self.recent_motion) / len(self.recent_motion)
        absorbed = 1.0 - min(1.0, abs(mot - 0.15) / 0.4)  # still but not frozen
        touch = 0.0
        if self.recent_touch_t and self.t_last is not None:
            touch = 1.0 if self.t_last - self.recent_touch_t[-1] < 5 else 0.0
        if self.recent_held_t is not None and self.t_last - self.recent_held_t < 2:
            touch = 1.0  # holding and turning the phone counts as engaged
        voice = (sum(self.recent_voice) / len(self.recent_voice)) if self.recent_voice else 0.0
        score = (0.30 * min(1.0, near / 0.5) + 0.15 * clamp(trend * 5, 0, 1)
                 + 0.25 * look + 0.15 * absorbed + 0.10 * touch + 0.05 * min(1.0, voice * 3))
        return clamp(score, 0.0, 1.0)
