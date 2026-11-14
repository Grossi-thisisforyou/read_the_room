# -*- coding: utf-8 -*-
"""INFINITE JEST phone agent for the Nokia N900.

Reads the phone's sensors, front camera and microphone level, and streams
them to the Pi show engine as JSON envelopes {type, ts, data}
(CONTRACT.md: "sensor" kind "phone" ~10 Hz, touch/choice/keys events,
"frame" gray8 160x120 at <= 4 fps). It receives "state", "phone" and
"wipe" from the engine and hands them to the screen (ui.py).

Runs on Python 2.5 (Maemo 5) and Python 3 (laptop tests):

    python agent.py                 # on the N900, with the full-screen UI
    python agent.py --headless      # no screen, sensors + network only
    python agent.py --fake --host 127.0.0.1 --headless   # laptop, synthetic sensors

Settings: defaults below, overridden by /home/user/.ij-phone.conf (or
--conf FILE), one `key = value` per line.
"""

import base64
import os
import random
import subprocess
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from compat import clamp, log, exc, loads, to_text, queue_mod, string_types, finite  # noqa: E402
from transport import WSClient, UDPSender, WSClosed  # noqa: E402
from sensors import Sensors, available  # noqa: E402
from capture import Camera, Mic  # noqa: E402

VERSION = '1.0'

DEFAULTS = {
    'hosts': '192.168.1.10,inartwetrust.local',   # tried in order
    'ws_port': 8765,
    'ws_path': '/ws',
    'udp_port': 8766,
    'rate_hz': 20.0,          # periodic sensor messages (visitors move the phone; tilt needs it)
    'frame_fps': 4.0,         # camera frames to the Pi (contract max 4)
    'frame_w': 160,
    'frame_h': 120,
    'camera_device': '/dev/video1',   # front camera; /dev/video0 is the rear 5 MP
    'camera': 1,
    'mic': 1,
    'frames': 1,              # send frames at all
    'frames_after_consent': 1,  # camera frames only after the visitor taps in (0 = always)
    'keep_awake': 1,          # MCE display blanking pause, tklock off
    'wifi_powersave_off': 1,
    'local_prompts': 1,       # show bundled either/or prompts when the Pi sends none
    'prompt_every_s': 25.0,
    'idle_reset_s': 90.0,     # back to the consent screen after this long with nobody
    'optout_release_s': 8.0,  # an opt-out lasts until the phone has been put down this long
    'name': 'n900',
}

CONF_PATH = '/home/user/.ij-phone.conf'


def load_conf(path):
    conf = dict(DEFAULTS)
    try:
        f = open(path, 'r')
    except (IOError, OSError):
        return conf
    try:
        for line in f:
            line = line.split('#')[0].strip()
            if '=' not in line:
                continue
            k, v = [p.strip() for p in line.split('=', 1)]
            if k in DEFAULTS and isinstance(DEFAULTS[k], (int, float)) and not isinstance(DEFAULTS[k], bool):
                try:
                    v = type(DEFAULTS[k])(float(v))
                except ValueError:
                    continue
            conf[k] = v
    finally:
        f.close()
    return conf


FALLBACK_PROMPTS = [
    ('l1', 'look closer?', ['closer', 'away']),
    ('l2', 'should it know you?', ['yes', 'no']),
    ('l3', 'stay or leave?', ['stay', 'leave']),
    ('l4', 'louder or quieter?', ['louder', 'quieter']),
    ('l5', 'are you alone here?', ['alone', 'not alone']),
]


def load_prompts():
    """Prompts from the profiling thread's file if it is next to us, else ours."""
    for p in (os.path.join(HERE, 'prompts.json'),
              os.path.join(HERE, 'text_prompts.json'),
              os.path.join(HERE, '..', '..', 'text', 'corpus', 'prompts.json'),
              os.path.join(HERE, 'profiler_prompts.json'),
              os.path.join(HERE, '..', '..', 'profiler', 'prompts.json'),
              os.path.join(HERE, '..', '..', 'profiling', 'prompts.json')):
        try:
            f = open(p, 'r')
            try:
                data = loads(f.read())
            finally:
                f.close()
            if isinstance(data, dict):
                data = data.get('prompts', [])
            out = []
            for d in data:
                opts = d.get('options') or []
                if d.get('ask') and len(opts) >= 2:
                    out.append((d.get('prompt_id') or d.get('id') or 'p', d['ask'], opts[:2]))
            if out:
                return out
        except Exception:
            continue
    return list(FALLBACK_PROMPTS)


def load_phone_text():
    """Consent versions and opt-out lines written for the phone (text/corpus/lines.json)."""
    consent, optout = [], []
    for p in (os.path.join(HERE, 'text_lines.json'),
              os.path.join(HERE, '..', '..', 'text', 'corpus', 'lines.json')):
        try:
            f = open(p, 'r')
            try:
                data = loads(f.read())
            finally:
                f.close()
        except Exception:
            continue
        items = isinstance(data, dict) and data.get('lines') or data
        for d in items or []:
            try:
                if d.get('surface') != 'phone':
                    continue
                if d.get('beat') == 'consent' and d.get('lines'):
                    consent.append(list(d['lines']))
                elif d.get('beat') == 'optout' and d.get('text') and len(d['text']) < 40:
                    optout.append(d['text'])
            except Exception:
                continue
        if consent or optout:
            break
    return consent, optout


class Peak(object):
    """Rises instantly, falls slowly: 'someone was just here'."""

    def __init__(self, fall=0.25):
        self.v = 0.0
        self.fall = fall
        self.t = time.time()

    def __call__(self, x, t):
        dt = max(0.0, t - self.t)   # the N900 clock can jump backwards
        self.t = t
        self.v = max(x, self.v - self.fall * dt)
        return self.v


class Agent(object):

    def __init__(self, conf, fake=False, sysfs_root=''):
        self.conf = conf
        self.fake = fake
        self.running = True
        self.sensors = Sensors(root=sysfs_root)
        self.camera = None
        self.mic = None
        if int(conf['camera']):
            self.camera = Camera(int(conf['frame_w']), int(conf['frame_h']),
                                 int(conf['frame_fps']), conf['camera_device'], fake=fake)
        if int(conf['mic']):
            self.mic = Mic(fake=fake)
        self.ws = None
        self.udp = None
        self.link = 'none'          # 'ws' | 'udp' | 'none'
        self.host = None
        self.events = queue_mod.Queue(200)
        self.presence = Peak(0.12)
        self.touch_t = 0.0
        self.near_since = None
        self.prox_armed = True      # after a wipe, proximity must read 'open' once before an opt-out
        self.opted_out = False
        self.clock_offset = None    # Pi clock minus N900 clock, from the engine's state ts
        self.mode = 'handheld'      # contract default; the engine's state.mode overrides
        self.held_t = 0.0           # last time the phone was in someone's hands (local only, never sent)
        self.optout_t = 0.0
        self.reading_t = 0.0
        self.lock = threading.Lock()
        self.listeners = []
        self.prompts = load_prompts()
        self.prompt_i = random.randint(0, len(self.prompts) - 1)
        self.consent_versions, self.optout_lines = load_phone_text()
        # shared with the UI
        self.ui = {
            'screen': 'consent',     # consent | live
            'engaged_t': 0.0,
            'state': {},             # last engine state
            'text': '', 'text_t': 0.0,
            'prompt': None,          # {prompt_id, ask, options, t}
            'last_pi_phone_t': 0.0,
            'reading': {},           # last periodic reading (for the "dark data" readout)
            'link': 'none',
            'wiped_t': 0.0,
            'last_presence_t': time.time(),
            'optout': False,
            'consent': None,         # this visit's consent text (None = built-in)
            'optout_text': None,
        }
        self.new_visit_text()

    def new_visit_text(self):
        """Each visitor gets one of the written consent versions."""
        kw = {}
        if self.consent_versions:
            kw['consent'] = random.choice(self.consent_versions)
        if self.optout_lines:
            kw['optout_text'] = random.choice([l for l in self.optout_lines
                                               if 'not being read' not in l] or self.optout_lines)
        self.ui_update(**kw)

    # ------------------------------------------------------------ util --
    def ui_update(self, **kw):
        self.lock.acquire()
        try:
            self.ui.update(kw)
        finally:
            self.lock.release()

    def ui_snapshot(self):
        self.lock.acquire()
        try:
            return dict(self.ui)
        finally:
            self.lock.release()

    def now(self):
        """Unix time on the Pi's clock (the contract's reference).

        After a battery pull the N900 clock can be years off, so outgoing `ts`
        uses the offset learned from the engine's own `state` timestamps."""
        t = time.time()
        if self.clock_offset is not None:
            t += self.clock_offset
        return t

    def learn_clock(self, ts):
        try:
            ts = float(ts)
        except (TypeError, ValueError):
            return
        if not finite(ts) or ts < 1.0e9:
            return  # ts 0 / junk: not a clock reading
        off = ts - time.time()
        if self.clock_offset is None or abs(off - self.clock_offset) > 2.0:
            if abs(off - (self.clock_offset or 0.0)) > 60:
                log('clock: N900 differs from the Pi by %.1f s' % off)
            self.clock_offset = off
        else:
            # smooth out network jitter
            self.clock_offset += 0.1 * (off - self.clock_offset)

    def emit(self, typ, data):
        if self.opted_out and data.get('kind') in ('choice', 'keys', 'touch'):
            return
        msg = {'type': typ, 'ts': self.now(), 'data': data}
        try:
            self.events.put_nowait(msg)
        except Exception:
            pass  # queue full: drop, live data only

    # ------------------------------------------------- UI entry points --
    def on_consent(self):
        self.ui_update(screen='live', engaged_t=time.time(), text='', prompt=None)
        self.emit('sensor', {'kind': 'touch', 'x': 0.5, 'y': 0.5, 'down': False,
                             'gesture': 'enter', 'duration_ms': 0})

    def on_touch(self, x, y, down, gesture=None, duration_ms=None):
        self.touch_t = time.time()
        d = {'kind': 'touch', 'x': round(clamp(x), 3), 'y': round(clamp(y), 3), 'down': bool(down)}
        if gesture:
            d['gesture'] = gesture
        if duration_ms is not None:
            d['duration_ms'] = int(duration_ms)
        self.emit('sensor', d)

    def on_choice(self, option_index):
        snap = self.ui_snapshot()
        p = snap.get('prompt')
        if not p:
            return
        opts = p.get('options') or []
        if option_index >= len(opts):
            return
        latency = int((time.time() - p.get('t', time.time())) * 1000)
        self.emit('sensor', {'kind': 'choice', 'prompt_id': p.get('prompt_id'),
                             'option': opts[option_index], 'latency_ms': latency,
                             'local': bool(p.get('local'))})
        self.ui_update(prompt=None, text=opts[option_index], text_t=time.time())

    def on_keys(self, text, typing_ms=None, backspaces=None):
        d = {'kind': 'keys', 'text': text}
        if typing_ms is not None:
            d['typing_ms'] = int(typing_ms)
        if backspaces is not None:
            d['backspaces'] = int(backspaces)
        self.emit('sensor', d)

    # ------------------------------------------------- engine messages --
    def handle(self, msg):
        if not isinstance(msg, dict):
            return
        typ = msg.get('type')
        data = msg.get('data') or {}
        if not isinstance(data, dict):
            return
        if typ == 'state':
            self.learn_clock(msg.get('ts'))
            if data.get('mode') in ('handheld', 'fixed'):
                self.mode = data['mode']
            self.ui_update(state=data)
            if data.get('phase') == 'idle' and self.ui_snapshot()['screen'] == 'live':
                pass  # the engine's idle doesn't kick a visitor who is typing
        elif typ == 'phone':
            kw = {'last_pi_phone_t': time.time()}
            text = _short(data.get('text'), 160)
            if text:
                kw['text'] = text
                kw['text_t'] = time.time()
            opts = data.get('options')
            if isinstance(opts, string_types) or not isinstance(opts, (list, tuple)):
                opts = []
            opts = [_short(o, 32) for o in opts[:2]]
            ask = _short(data.get('ask'), 100)
            if ask and len(opts) >= 2 and opts[0] and opts[1]:
                kw['prompt'] = {'prompt_id': _short(data.get('prompt_id'), 64), 'ask': ask,
                                'options': opts, 't': time.time()}
            elif ask and not data.get('options'):
                # an open question (the engine's "What do you never tell anyone?"):
                # show it as words; the visitor answers on the slide-out keyboard
                kw['text'] = ask
                kw['text_t'] = time.time()
            self.ui_update(**kw)
        elif typ == 'wipe':
            self.wipe(from_engine=True)

    def wipe(self, from_engine=False):
        log('wipe')
        if self.camera:
            self.camera.wipe()
        while True:
            try:
                self.events.get_nowait()
            except Exception:
                break
        if self.opted_out and self.reading_t - self.held_t < float(self.conf['optout_release_s']):
            # The engine ends the visit soon after an opt-out (the phone stops
            # sending readings), but the same visitor may still be holding the
            # phone. "The eye is closed until you leave": stay closed until the
            # phone has been put down for optout_release_s (see reading()).
            self.ui_update(text='', prompt=None, state={}, reading={}, wiped_t=time.time())
            return
        self.opted_out = False
        self.near_since = None
        self.prox_armed = False   # phone still face-down on the plinth must not re-opt-out
        self._pause_capture(False)
        self.ui_update(screen='consent', text='', prompt=None, state={},
                       reading={}, wiped_t=time.time(), optout=False)
        self.new_visit_text()

    # ----------------------------------------------------------- loops --
    def reading(self, t):
        r = self.sensors.poll(t)
        handling = r.pop('_handling', 0.0)
        r.pop('_lens_open', None)
        motion = 0.0
        if self.camera and self.camera.alive():
            motion = self.camera.motion
            r['motion'] = round(motion, 3)
            if 'light' not in r:
                r['light'] = round(self.camera.brightness, 3)
        if self.mic and self.mic.alive():
            r['loudness'] = round(self.mic.level, 3)
            r['audio'] = {'level': round(self.mic.level, 3), 'voiced': bool(self.mic.voiced)}
        near = r.get('proximity', {}).get('near') and 1.0 or 0.0
        touched = (t - self.touch_t) < 3.0 and 1.0 or 0.0
        voiced = r.get('audio', {}).get('voiced') and 0.7 or 0.0
        held = r.get('held') and 0.8 or 0.0
        # A covered proximity sensor only means "a hand" while the phone is
        # being held; lying face-down on the plinth it is just the plinth.
        hand = max(handling, touched, held, held and near or 0.0)
        room = max(clamp(motion * 3.0), voiced)
        if self.mode != 'fixed':
            # handheld (contract default): people walking past the camera or
            # talking in the lounge are not a visitor until someone picks the
            # phone up -- same rule as the engine's Presence (max 0.4)
            room = min(room, 0.4)
        p = self.presence(max(hand, room), t)
        r['presence'] = round(p, 3)
        r['kind'] = 'phone'
        # Opt-out: covering the proximity sensor ("the eye") for 3 s stops all
        # reading of this visitor until the next wipe. After a wipe the sensor
        # has to read open once first, so a phone left face-down does not
        # opt every following visit out in a loop.
        if near:
            if self.near_since is None and self.prox_armed:
                self.near_since = t
            elif (self.near_since is not None and not self.opted_out
                  and t - self.near_since >= 3.0):
                self.opt_out(t)
        else:
            self.near_since = None
            self.prox_armed = True
        self.reading_t = t
        if r.get('held') or touched:
            self.held_t = t
        if self.opted_out:
            # One rule ends an opt-out: the phone has been out of anyone's hands
            # (accelerometer + touch only, never camera or mic) for
            # optout_release_s. A covered sensor keeps it closed, except when the
            # phone lies still face-down (that is the plinth, not a hand).
            tilt = r.get('tilt') or {}
            face_down = not r.get('held') and abs(tilt.get('beta', 0) or 0) > 168
            if ((not near or face_down)
                    and t - max(self.held_t, self.optout_t) >= float(self.conf['optout_release_s'])):
                self.opted_out = False      # put down: the opted-out visitor has left
                self.wipe()
            # keep only "is it in someone's hand" so the engine can end the visit
            return {'kind': 'phone', 'optout': True, 'held': bool(r.get('held'))}
        return r

    def opt_out(self, t=None):
        log('visitor opted out')
        self.opted_out = True
        self._pause_capture(True)
        self.optout_t = t is None and time.time() or t
        if self.camera:
            self.camera.wipe()
        self.emit('sensor', {'kind': 'optout'})
        self.ui_update(optout=True, prompt=None, text='')

    def _pause_capture(self, paused):
        if self.camera:
            self.camera.paused = paused
        if self.mic:
            self.mic.paused = paused

    def net_loop(self):
        hosts = [h.strip() for h in str(self.conf['hosts']).split(',') if h.strip()]
        backoff = 1.0
        while self.running:
            for h in hosts:
                if not self.running:
                    return
                ws = WSClient(h, self.conf['ws_port'], self.conf['ws_path'], timeout=4.0)
                try:
                    ws.connect()
                except Exception:
                    log('ws', h, 'failed:', exc())
                    if self.udp is None or self.host is None:
                        # UDP lane to the first host until the WebSocket is back
                        self.udp = UDPSender(hosts[0], self.conf['udp_port'])
                        self.set_link('udp', hosts[0])
                    continue
                log('ws connected to', h)
                backoff = 1.0
                self.ws = ws
                self.set_link('ws', h)
                try:
                    ws.send_json({'type': 'hello', 'ts': self.now(),
                                  'data': {'role': 'phone', 'device': 'n900',
                                           'name': self.conf['name'], 'version': VERSION}})
                    self.reader(ws)
                except Exception:
                    log('ws lost:', exc())
                self.ws = None
                ws.close()
                self.set_link('udp', h)
                if self.udp is not None:
                    self.udp.close()
                self.udp = UDPSender(h, self.conf['udp_port'])
            time.sleep(backoff)
            backoff = min(backoff * 1.7, 10.0)

    def set_link(self, link, host):
        self.link = link
        self.host = host
        self.ui_update(link=link)

    def reader(self, ws):
        while self.running and ws.open:
            try:
                text = ws.recv_text()
            except WSClosed:
                return
            try:
                self.handle(loads(text))
            except Exception:
                log('bad message:', exc())

    def send(self, msg, allow_udp=True):
        ws = self.ws
        if ws is not None and ws.open:
            try:
                ws.send_json(msg)
                return True
            except Exception:
                log('send failed:', exc())
                ws.open = False
        if allow_udp and self.udp is not None and msg.get('type') == 'sensor':
            self.udp.send_json(msg)
            return True
        return False

    def send_loop(self):
        period = 1.0 / float(self.conf['rate_hz'])
        frame_period = 1.0 / max(0.5, min(4.0, float(self.conf['frame_fps'])))
        last_frame_t = 0.0
        last_seq = -1
        next_t = time.time()
        while self.running:
            t = time.time()
            # events first, as soon as they happen
            while True:
                try:
                    m = self.events.get_nowait()
                except Exception:
                    break
                self.send(m)
            if t >= next_t:
                next_t = t + period
                r = self.reading(t)
                self.ui_update(reading=r)
                if r.get('presence', 0) > 0.45:   # the engine's on_threshold
                    self.ui_update(last_presence_t=t)
                self.send({'type': 'sensor', 'ts': self.now(), 'data': r})
                self.local_director(t)
            if (self.camera and int(self.conf['frames']) and self.link == 'ws'
                    and t - last_frame_t >= frame_period):
                snap_screen = self.ui['screen']
                if not self.opted_out and (not int(self.conf['frames_after_consent'])
                                           or snap_screen == 'live'):
                    frame, seq = self.camera.latest()
                    if frame is not None and seq != last_seq:
                        last_seq = seq
                        last_frame_t = t
                        self.send({'type': 'frame', 'ts': self.now(), 'data': {
                            'w': self.camera.w, 'h': self.camera.h, 'fmt': 'gray8',
                            'b64': to_text(base64.b64encode(frame))}}, allow_udp=False)
            time.sleep(0.02)

    def local_director(self, t):
        """When the Pi is silent, the phone keeps the visitor company itself."""
        snap = self.ui_snapshot()
        if snap['last_presence_t'] > t + 5:
            self.ui_update(last_presence_t=t)   # the N900 clock jumped backwards
        if snap['screen'] == 'live' and not self.opted_out:   # opt-out ends in reading()
            if t - snap['last_presence_t'] > float(self.conf['idle_reset_s']):
                log('nobody here, back to the consent screen')
                self.wipe()
                return
            if (int(self.conf['local_prompts']) and not snap['prompt']
                    and not self.opted_out and t - snap['last_pi_phone_t'] > 30.0
                    and t - max(snap['engaged_t'], snap['text_t']) > float(self.conf['prompt_every_s'])):
                pid, ask, opts = self.prompts[self.prompt_i % len(self.prompts)]
                self.prompt_i += 1
                self.ui_update(prompt={'prompt_id': pid, 'ask': ask, 'options': opts,
                                       't': t, 'local': True}, text_t=t)

    def keep_awake_loop(self):
        """Keep the display on and unlocked for hours (Maemo MCE over D-Bus)."""
        n = 0
        while self.running:
            if int(self.conf['wifi_powersave_off']) and n % 6 == 0:
                # again every minute: a Wi-Fi reconnect turns power saving back on
                _run('/sbin/iwconfig wlan0 power off')
            n += 1
            _run('dbus-send --system --type=method_call --dest=com.nokia.mce '
                 '/com/nokia/mce/request com.nokia.mce.request.req_display_blanking_pause')
            _run('dbus-send --system --type=method_call --dest=com.nokia.mce '
                 '/com/nokia/mce/request com.nokia.mce.request.req_tklock_mode_change '
                 'string:unlocked')
            time.sleep(10)  # also undoes a visitor's power-button lock within 10 s

    # ----------------------------------------------------------- start --
    def start(self):
        log('INFINITE JEST phone agent', VERSION, 'fake' if self.fake else '',
            'sensors:', ','.join(available()) or 'none')
        if not self.fake and 'proximity' not in available():
            log('WARNING: no proximity sensor file, so the cover-to-opt-out gesture cannot work')
        if self.camera:
            self.camera.start()
        if self.mic:
            self.mic.start()
        loops = [self.net_loop, self.send_loop]
        if int(self.conf['keep_awake']) and not self.fake:
            loops.append(self.keep_awake_loop)
        for fn in loops:
            th = threading.Thread(target=fn)
            th.setDaemon(True)
            th.start()

    def stop(self):
        self.running = False
        if self.camera:
            self.camera.stop()
        if self.mic:
            self.mic.stop()
        if self.ws:
            self.ws.close()


def _short(v, n):
    """Engine text for the screen: a string, at most n characters."""
    if v is None or isinstance(v, bool):
        return ''
    if not isinstance(v, string_types):
        if isinstance(v, (dict, list, tuple)):
            return ''
        v = str(v)
    return v[:n]


def _run(cmd):
    devnull = None
    try:
        devnull = open(os.devnull, 'w')
        subprocess.call(cmd, shell=True, stdout=devnull, stderr=devnull)
    except Exception:
        pass
    if devnull is not None:
        devnull.close()


def main(argv):
    conf_path = CONF_PATH
    fake = os.environ.get('FAKE') == '1'
    headless = False
    sysfs = ''
    host = None
    i = 1
    while i < len(argv):
        a = argv[i]
        if a == '--fake':
            fake = True
        elif a == '--headless':
            headless = True
        elif a == '--conf':
            i += 1
            conf_path = argv[i]
        elif a == '--host':
            i += 1
            host = argv[i]
        elif a == '--sysfs':
            i += 1
            sysfs = argv[i]
        i += 1
    conf = load_conf(conf_path)
    if host:
        conf['hosts'] = host
    agent = Agent(conf, fake=fake, sysfs_root=sysfs)
    agent.start()
    if not headless:
        try:
            import ui
        except Exception:
            log('no screen (', exc(), '), running headless')
            headless = True
    if headless:
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        ui.run(agent)
    agent.stop()


if __name__ == '__main__':
    main(sys.argv)
