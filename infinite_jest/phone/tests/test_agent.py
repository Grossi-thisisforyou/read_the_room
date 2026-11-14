"""End-to-end test: the N900 agent (fake sensors) against a mock Pi engine.

    pip install websockets
    python3 test_agent.py

Checks hello, periodic sensor messages, gray8 frames, prompts from the Pi,
choices, the proximity opt-out, wipe, the UDP fallback and reconnect.
"""
import asyncio, base64, json, os, socket, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, '..', 'n900'))
import websockets
from agent import Agent, DEFAULTS

def _free(kind):
    s = socket.socket(socket.AF_INET, kind)
    s.bind(('127.0.0.1', 0))
    p = s.getsockname()[1]
    s.close()
    return p


# free ports, so parallel runs (or a running engine) don't collide
PORT, UDP = _free(socket.SOCK_STREAM), _free(socket.SOCK_DGRAM)
got = {'types': [], 'sensor_kinds': [], 'frames': [], 'udp': [], 'choices': [], 'hello': None}
clients = []


async def handler(ws):
    clients.append(ws)
    async for raw in ws:
        m = json.loads(raw)
        got['types'].append(m['type'])
        if m['type'] == 'hello':
            got['hello'] = m['data']
            await ws.send(json.dumps({'type': 'state', 'ts': time.time(), 'data': {
                'phase': 'approach', 'hook': 'flesh', 'intensity': 0.7, 'tempo': 130,
                'palette': {'name': 'meat', 'colors': ['#c0503f']}, 'words': ['seen']}}))
        elif m['type'] == 'sensor':
            got['sensor_kinds'].append(m['data'].get('kind'))
            if m['data'].get('kind') == 'choice':
                got['choices'].append(m['data'])
            if m['data'].get('kind') == 'phone':
                got['last_phone'] = m['data']
        elif m['type'] == 'frame':
            got['frames'].append(m['data'])


def udp_listener():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(('127.0.0.1', UDP))
    while True:
        d, _ = s.recvfrom(65536)
        got['udp'].append(json.loads(d))


def fake_sysfs():
    root = tempfile.mkdtemp()
    files = {
        '/sys/class/i2c-adapter/i2c-3/3-001d/coord': '18 -36 -1008',
        '/sys/class/i2c-adapter/i2c-2/2-0029/lux': '35',
        '/sys/devices/platform/gpio-switch/proximity/state': 'open',
        '/sys/devices/platform/gpio-switch/slide/state': 'closed',
        '/sys/class/power_supply/bq27200-0/capacity': '81',
    }
    for p, v in files.items():
        os.makedirs(os.path.dirname(root + p), exist_ok=True)
        open(root + p, 'w').write(v)
    return root


def check(cond, what):
    print(('PASS ' if cond else 'FAIL ') + what)
    if not cond:
        check.failed = True
check.failed = False


async def main():
    threading.Thread(target=udp_listener, daemon=True).start()
    root = fake_sysfs()
    conf = dict(DEFAULTS, hosts='127.0.0.1', ws_port=PORT, udp_port=UDP, keep_awake=0)
    agent = Agent(conf, fake=True, sysfs_root=root)

    # 1) Pi not up yet: readings go over UDP
    agent.start()
    await asyncio.sleep(2.0)
    check(len(got['udp']) > 5 and got['udp'][0]['data'].get('seq'), 'UDP fallback while the Pi is down (%d)' % len(got['udp']))

    server = await websockets.serve(handler, '127.0.0.1', PORT)
    await asyncio.sleep(4.0)
    check(got['hello'] and got['hello'].get('role') == 'phone' and got['hello'].get('device') == 'n900', 'hello role phone')
    n = got['sensor_kinds'].count('phone')
    check(n >= 20, 'periodic sensor messages (%d in ~3 s)' % n)
    p = got.get('last_phone', {})
    for k in ('accel', 'tilt', 'light', 'presence', 'motion', 'audio', 'battery', 'held', 'proximity', 'slide'):
        check(k in p, 'sensor field ' + k)
    check(isinstance(p.get('held'), bool) and isinstance(p.get('audio', {}).get('voiced'), bool), 'held/voiced are bools')
    check(abs(p['accel']['z'] + 1.008) < 0.01, 'accel in g')
    check(len(got['frames']) == 0, 'no camera frames before the visitor taps in')
    agent.on_consent()
    await asyncio.sleep(2.5)
    f = got['frames'][-1] if got['frames'] else {}
    check(len(got['frames']) >= 6 and len(base64.b64decode(f.get('b64', ''))) == 160 * 120, 'gray8 frames 160x120 (%d)' % len(got['frames']))
    check(agent.ui_snapshot()['state'].get('hook') == 'flesh', 'state reaches the screen')

    # 2) consent, prompt from the Pi, choice
    agent.on_consent()
    ws = clients[-1]
    await ws.send(json.dumps({'type': 'phone', 'ts': 0, 'data': {'prompt_id': 'closer', 'ask': 'look closer?', 'options': ['closer', 'away']}}))
    await asyncio.sleep(0.5)
    check(agent.ui_snapshot()['prompt']['prompt_id'] == 'closer', 'prompt shows on the phone')
    agent.on_choice(1)
    agent.on_keys('i am not sure', 4200, 3)
    await asyncio.sleep(0.5)
    check(got['choices'] and got['choices'][-1]['option'] == 'away' and 'latency_ms' in got['choices'][-1], 'choice sent with exact option + latency')
    check('keys' in got['sensor_kinds'], 'keys event sent')

    # 3) opt-out: cover the proximity sensor for 3 s
    prox = root + '/sys/devices/platform/gpio-switch/proximity/state'
    open(prox, 'w').write('closed')
    await asyncio.sleep(3.6)
    nframes = len(got['frames'])
    check('optout' in got['sensor_kinds'] and agent.ui_snapshot()['optout'], 'opt-out after 3 s covered')
    await asyncio.sleep(1.0)
    lp = dict(got['last_phone'])
    check(len(got['frames']) == nframes and lp.pop('held', None) in (True, False)
          and lp == {'kind': 'phone', 'optout': True}, 'nothing but "held" is read after opt-out')
    open(prox, 'w').write('open')

    # 4) wipe
    await ws.send(json.dumps({'type': 'wipe', 'ts': 0, 'data': {'visitor_id': 'v-1'}}))
    await asyncio.sleep(0.5)
    s = agent.ui_snapshot()
    check(s['screen'] == 'consent' and not s['optout'] and s['state'] == {}, 'wipe returns to consent and clears')
    agent.on_consent()
    await asyncio.sleep(0.8)
    check(len(got['frames']) > nframes, 'reading resumes for the next visitor')

    # 5) reconnect
    server.close()
    await server.wait_closed()
    for c in list(clients):
        await c.close()
    hellos = got['types'].count('hello')
    await asyncio.sleep(2.0)
    server = await websockets.serve(handler, '127.0.0.1', PORT)
    await asyncio.sleep(6.0)
    check(got['types'].count('hello') > hellos, 'reconnects after the Pi restarts')
    agent.stop()
    server.close()
    print('FAILED' if check.failed else 'ALL PASSED')


def test_agent_end_to_end():
    asyncio.run(main())
    assert not check.failed


if __name__ == '__main__':
    asyncio.run(main())
    sys.exit(1 if check.failed else 0)
