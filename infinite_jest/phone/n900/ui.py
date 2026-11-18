# -*- coding: utf-8 -*-
"""Full-screen PyGTK window for the N900 (PyMaemo: pygtk + pycairo).

Input:
- consent screen: a tap anywhere enters.
- live: taps/holds/swipes go to the Pi as touch events; when a prompt is up,
  the left or right half (or keys 1 / 2) answers it.
- slide-out keyboard: typing shows a line at the bottom, Enter sends it as a
  "keys" event with how long it took and how often they deleted.
- maintenance: hold the top-left corner for 5 s to quit (no keyboard shortcut,
  so a visitor typing on the keyboard can't close it).
"""

import time

import gobject
import gtk

import screens

try:
    import hildon
except ImportError:
    hildon = None

FPS = 10   # the N900's CPU draws a full 800x480 cairo frame in roughly 50-100 ms


class Screen(object):

    def __init__(self, agent):
        self.agent = agent
        self.local = {'buffer': '', 'typing': False, 'backspaces': 0, 'type_start': 0.0,
                      'last_key_t': 0.0}
        self.down = None   # (x, y, t)
        if hildon is not None:
            self.win = hildon.Window()
        else:
            self.win = gtk.Window()
        self.win.set_title('INFINITE JEST')
        self.win.connect('destroy', self.quit)
        self.area = gtk.DrawingArea()
        self.area.set_events(gtk.gdk.EXPOSURE_MASK | gtk.gdk.BUTTON_PRESS_MASK |
                             gtk.gdk.BUTTON_RELEASE_MASK | gtk.gdk.POINTER_MOTION_MASK)
        self.area.connect('expose-event', self.expose)
        self.area.connect('button-press-event', self.press)
        self.area.connect('button-release-event', self.release)
        self.win.connect('key-press-event', self.key)
        self.win.add(self.area)
        self.win.show_all()
        self.win.fullscreen()
        try:
            # ask hildon-desktop to keep the display on while we are on top
            self.win.window.property_change('_HILDON_DO_NOT_DISTURB', 'INTEGER', 32,
                                            gtk.gdk.PROP_MODE_REPLACE, [1])
        except Exception:
            pass
        gobject.timeout_add(int(1000 / FPS), self.tick)

    def quit(self, *a):
        gtk.main_quit()

    def tick(self):
        snap = self.agent.ui_snapshot()
        if snap.get('screen') != 'live' and self.local['buffer']:
            self.local.update({'buffer': '', 'typing': False, 'backspaces': 0})
        self.area.queue_draw()
        return True

    def expose(self, widget, event):
        cr = widget.window.cairo_create()
        w, h = widget.window.get_size()
        try:
            screens.draw(cr, w, h, self.agent.ui_snapshot(), self.local, time.time())
        except Exception:
            pass  # a drawing bug must never take the phone down
        return True

    def size(self):
        return self.area.window.get_size()

    def press(self, widget, ev):
        w, h = self.size()
        self.down = (ev.x, ev.y, time.time())
        if self.agent.ui_snapshot().get('screen') == 'live':
            self.agent.on_touch(ev.x / w, ev.y / h, True)
        return True

    def release(self, widget, ev):
        if self.down is None:
            return True
        w, h = self.size()
        x0, y0, t0 = self.down
        self.down = None
        dur = (time.time() - t0) * 1000.0
        if x0 < 60 and y0 < 60 and ev.x < 60 and ev.y < 60 and dur > 5000:
            self.quit()
            return True
        snap = self.agent.ui_snapshot()
        if snap.get('screen') != 'live':
            self.agent.on_consent()
            return True
        moved = abs(ev.x - x0) / w + abs(ev.y - y0) / h
        if moved > 0.08:
            gesture = 'swipe'
        elif dur > 600:
            gesture = 'hold'
        else:
            gesture = 'tap'
        self.agent.on_touch(ev.x / w, ev.y / h, False, gesture, dur)
        if snap.get('prompt') and gesture == 'tap':
            self.agent.on_choice(ev.x < w / 2 and 0 or 1)
        return True

    def key(self, widget, ev):
        name = gtk.gdk.keyval_name(ev.keyval) or ''
        snap = self.agent.ui_snapshot()
        if snap.get('screen') != 'live':
            self.agent.on_consent()
            return True
        L = self.local
        now = time.time()
        if snap.get('prompt') and not L['buffer'] and name in ('1', '2'):
            self.agent.on_choice(int(name) - 1)
            return True
        if name in ('Return', 'KP_Enter'):
            if L['buffer'].strip():
                self.agent.on_keys(L['buffer'], (now - L['type_start']) * 1000.0, L['backspaces'])
            L.update({'buffer': '', 'typing': False, 'backspaces': 0})
            return True
        if name == 'BackSpace':
            L['buffer'] = L['buffer'][:-1]
            L['backspaces'] += 1
            return True
        ch = ev.string
        if ch and len(ch) == 1 and ord(ch) >= 32:
            if not L['typing']:
                L['typing'] = True
                L['type_start'] = now
            L['buffer'] = (L['buffer'] + ch)[-60:]
            L['last_key_t'] = now
        return True


def run(agent):
    gobject.threads_init()
    Screen(agent)
    gtk.main()
