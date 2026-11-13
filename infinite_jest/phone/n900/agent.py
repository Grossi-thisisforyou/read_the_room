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

from compat import clamp, log, exc, loads, to_text, queue_mod  # noqa: E402
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
    'frames_after_consent': 0,  # 1 = only send camera frames after the visitor taps in
    'keep_awake': 1,          # MCE display blanking pause, tklock off
    'wifi_powersave_off': 1,
    'local_prompts': 1,       # show bundled either/or prompts when the Pi sends none
    'prompt_every_s': 25.0,
    'idle_reset_s': 90.0,     # back to the consent screen after this long with nobody
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


class Peak(object):
    """Rises instantly, falls slowly: 'someone was just here'."""

    def __init__(self, fall=0.25):
        self.v = 0.0
        self.fall = fall
        self.t = time.time()

    def __call__(self, x, t):
        dt = t - self.t
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
        self.opted_out = False
        self.lock = threading.Lock()
        self.listeners = []
        self.prompts = load_prompts()
        self.prompt_i = random.randint(0, len(self.prompts) - 1)
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
        }

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

    def emit(self, typ, data):
        if self.opted_out and data.get('kind') in ('choice', 'keys', 'touch'):
            return
        msg = {'type': typ, 'ts': time.time(), 'data': data}
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
        typ = msg.get('type')
        data = msg.get('data') or {}
        if typ == 'state':
            self.ui_update(state=data)
            if data.get('phase') == 'idle' and self.ui_snapshot()['screen'] == 'live':
                pass  # the engine's idle doesn't kick a visitor who is typing
        elif typ == 'phone':
            kw = {'last_pi_phone_t': time.time()}
            if data.get('text'):
                kw['text'] = data['text']
                kw['text_t'] = time.time()
            if data.get('ask') and len(data.get('options') or []) >= 2:
                kw['prompt'] = {'prompt_id': data.get('prompt_id'), 'ask': data['ask'],
                                'options': list(data['options'])[:2], 't': time.time()}
            self.ui_update(**kw)
        elif typ == 'wipe':
            self.wipe()

    def wipe(self):
        log('wipe')
        if self.camera:
            self.camera.wipe()
        while True:
            try:
                self.events.get_nowait()
            except Exception:
                break
        self.opted_out = False
        self.near_since = None
        self.ui_update(screen='consent', text='', prompt=None, state={},
                       reading={}, wiped_t=time.time(), optout=False)

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
        p = self.presence(max(clamp(motion * 3.0), handling, near, touched, voiced,
                              r.get('held') and 0.8 or 0.0), t)
        r['presence'] = round(p, 3)
        r['kind'] = 'phone'
        # Opt-out: covering the proximity sensor ("the eye") for 3 s stops all
        # reading of this visitor until the next wipe.
        if near:
            if self.near_since is None:
                self.near_since = t
            elif not self.opted_out and t - self.near_since >= 3.0:
                self.opt_out()
        else:
            self.near_since = None
        if self.opted_out:
            return {'kind': 'phone', 'optout': True}
        return r

    def opt_out(self):
        log('visitor opted out')
        self.opted_out = True
        if self.camera:
            self.camera.wipe()
        self.emit('sensor', {'kind': 'optout'})
        self.ui_update(optout=True, prompt=None, text='')

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
                    ws.send_json({'type': 'hello', 'ts': time.time(),
                                  'data': {'role': 'phone', 'device': 'n900',
                                           'name': self.conf['name'], 'version': VERSION}})
                    self.reader(ws)
                except Exception:
                    log('ws lost:', exc())
                self.ws = None
                ws.close()
                self.set_link('udp', h)
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
                if r.get('presence', 0) > 0.3:
                    self.ui_update(last_presence_t=t)
                self.send({'type': 'sensor', 'ts': t, 'data': r})
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
                        self.send({'type': 'frame', 'ts': t, 'data': {
                            'w': self.camera.w, 'h': self.camera.h, 'fmt': 'gray8',
                            'b64': to_text(base64.b64encode(frame))}}, allow_udp=False)
            time.sleep(0.02)

    def local_director(self, t):
        """When the Pi is silent, the phone keeps the visitor company itself."""
        snap = self.ui_snapshot()
        if snap['screen'] == 'live':
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
        if int(self.conf['wifi_powersave_off']):
            _run('/sbin/iwconfig wlan0 power off')
        while self.running:
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


def _run(cmd):
    try:
        devnull = open(os.devnull, 'w')
        subprocess.call(cmd, shell=True, stdout=devnull, stderr=devnull)
    except Exception:
        pass


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
