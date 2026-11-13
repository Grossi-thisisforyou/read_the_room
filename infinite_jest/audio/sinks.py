"""Audio outputs: aplay pipe (Pi), sounddevice (Mac/laptop), or a paced null sink."""
import shutil
import subprocess
import sys
import time

SR = 48000


class NullSink:
    """Discards audio but keeps real-time pacing so the render loop does not spin."""
    name = "null"

    def __init__(self, block=1024):
        self.dt = block / float(SR)
        self.t = None

    def write(self, frames):
        now = time.monotonic()
        if self.t is None or now - self.t > 0.5:
            self.t = now
        self.t += self.dt
        d = self.t - now - 0.15          # allow ~150 ms of render-ahead
        if d > 0:
            time.sleep(d)

    def close(self):
        pass


class AplaySink:
    name = "aplay"

    def __init__(self, device="default", latency_ms=150):
        cmd = ["aplay", "-q", "-D", str(device), "-f", "S16_LE", "-r", str(SR), "-c", "2",
               "-t", "raw", "-B", str(int(latency_ms * 1000))]
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE)
        try:   # shrink the pipe so it adds ~40 ms, not ~340 ms, of latency
            import fcntl
            fcntl.fcntl(self.p.stdin.fileno(), 1031, 8192)   # F_SETPIPE_SZ
        except Exception:
            pass

    def write(self, frames):
        if self.p.poll() is not None:
            raise IOError("aplay exited with code %s" % self.p.returncode)
        self.p.stdin.write(frames.tobytes())

    def close(self):
        try:
            self.p.stdin.close()
        except Exception:
            pass
        try:
            self.p.wait(timeout=2)
        except Exception:
            self.p.kill()


class SoundDeviceSink:
    name = "sounddevice"

    def __init__(self, device="default", latency_ms=150, block=1024):
        import sounddevice as sd
        dev = None if device in (None, "", "default") else device
        self.s = sd.RawOutputStream(samplerate=SR, channels=2, dtype="int16", device=dev,
                                    blocksize=block, latency=latency_ms / 1000.0)
        self.s.start()

    def write(self, frames):
        self.s.write(frames.tobytes())

    def close(self):
        try:
            self.s.stop()
            self.s.close()
        except Exception:
            pass


def open_sink(config, block=1024):
    kind = str(config.get("audio_sink", "auto")).lower()
    dev = config.get("audio_device", "default") or "default"
    lat = float(config.get("audio_latency_ms", 150))
    if kind == "null":
        return NullSink(block)
    if kind in ("auto", "aplay") and shutil.which("aplay"):
        try:
            return AplaySink(dev, lat)
        except Exception as e:
            print("[audio] aplay failed: %s" % e, file=sys.stderr)
    if kind in ("auto", "sounddevice", "aplay"):
        try:
            return SoundDeviceSink(dev, lat, block)
        except Exception as e:
            print("[audio] sounddevice unavailable: %s" % e, file=sys.stderr)
    print("[audio] no audio output found; running silent (null sink)", file=sys.stderr)
    return NullSink(block)
