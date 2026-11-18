"""Render the N900 screens to PNG (800x480, the N900's resolution) for review."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'n900'))
import cairo
import screens

OUT = sys.argv[1] if len(sys.argv) > 1 else '.'
reading = {'kind': 'phone', 'tilt': {'alpha': 0, 'beta': -14.2, 'gamma': 6.0}, 'held': True,
           'audio': {'level': 0.62, 'voiced': True}, 'motion': 0.31, 'light': 0.22,
           'presence': 0.87, 'proximity': {'near': False}}
state = {'phase': 'hook', 'hook': 'flesh', 'intensity': 0.8, 'tempo': 132,
         'palette': {'name': 'meat', 'colors': ['#c0503f', '#5a0d0b', '#e8d9a8']},
         'words': ['you looked away 3 times', 'stillness 0.8', 'neuroticism?', 'open']}
cases = {
    'consent': ({'screen': 'consent', 'link': 'ws'}, {}),
    'live': ({'screen': 'live', 'link': 'ws', 'state': state, 'reading': reading,
              'text': 'you came closer', 'text_t': 0}, {'backspaces': 2}),
    'prompt': ({'screen': 'live', 'link': 'udp', 'state': state, 'reading': reading,
                'prompt': {'prompt_id': 'closer', 'ask': 'look closer?', 'options': ['closer', 'away']}}, {}),
    'typing': ({'screen': 'live', 'link': 'ws', 'state': dict(state, hook='inverted'),
                'reading': dict(reading, slide=True)}, {'typing': True, 'buffer': 'i am not sure what i', 'backspaces': 4}),
    'optout': ({'screen': 'live', 'optout': True, 'link': 'ws'}, {}),
}
for name, (snap, local) in cases.items():
    surf = cairo.ImageSurface(cairo.FORMAT_RGB24, 800, 480)
    cr = cairo.Context(surf)
    t0 = time.time()
    screens.draw(cr, 800, 480, snap, local, 1000.4)
    surf.write_to_png(os.path.join(OUT, 'n900-%s.png' % name))
    print(name, '%.1f ms' % ((time.time() - t0) * 1000))
