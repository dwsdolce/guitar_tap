#!/usr/bin/env python3
"""Guitar Tap Mic Probe — records one microphone several ways at once and reports the levels.

A standalone diagnostic to send to a user whose microphone reads far quieter in
Guitar Tap than in other apps. It opens the SAME physical mic through several
PortAudio configurations simultaneously, so every configuration hears the same
taps:

  gtap        exactly how Guitar Tap opens it: WASAPI, 1 channel, device default
              rate, float32, blocksize 1024 (PortAudio does any downmix)
  wasapi-N    WASAPI with the endpoint's native channel count (no downmix)
  mme-N       MME with its native channel count     (what many older apps use)
  dsound-N    DirectSound with its native channel count

For each it writes a WAV (all channels kept) and reports per-channel peak,
loudest 1024-sample chunk RMS (the level Guitar Tap's tap detector compares with
the Threshold), noise floor, and the correlation between channels — a strongly
negative correlation means the channels are phase-inverted, so averaging them to
mono (what PortAudio does for the ``gtap`` stream) cancels the signal.

Everything lands in a folder and a .zip on the Desktop.

    python Tooling/mic-probe/mic_probe.py                 # interactive
    python Tooling/mic-probe/mic_probe.py --list          # devices only
    python Tooling/mic-probe/mic_probe.py --device 3 --seconds 20 --yes

Build a Windows exe with Tooling/mic-probe/build_win.bat — build it from the SAME
.venv as the release, so it carries the same sounddevice/PortAudio DLL.

Python-only diagnostic; no Swift counterpart.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import platform
import struct
import sys
import threading
import time
import zipfile

import numpy as np
import sounddevice as sd

PROBE_VERSION = "1.0"
CHUNK = 1024           # Guitar Tap's blocksize; its detector level is per-chunk RMS
QUIET_SECONDS = 5.0    # leading window the user keeps quiet — the noise floor
GTAP_MIN_THRESHOLD_DB = -80.0   # bottom of Guitar Tap's Threshold slider


# ── Device discovery ─────────────────────────────────────────────────────────

def host_api_name(dev: dict) -> str:
    return str(sd.query_hostapis(int(dev["hostapi"]))["name"])


def all_inputs() -> "list[dict]":
    out = []
    for d in sd.query_devices():
        if int(d["max_input_channels"]) > 0:
            d = dict(d)
            d["_api"] = host_api_name(d)
            out.append(d)
    return out


def gtap_device_list(inputs: "list[dict]") -> "list[dict]":
    """The inputs Guitar Tap offers — mirrors models/audio_device.filter_input_devices."""
    if platform.system() != "Windows":
        return inputs
    apis = {d["_api"] for d in inputs}
    preferred = next((a for a in ("Windows WASAPI", "Windows DirectSound", "MME") if a in apis), None)
    pseudo = ("microsoft sound mapper", "primary sound capture")
    out = []
    for d in inputs:
        n = d["name"].lower()
        if any(p in n for p in pseudo) or "loopback" in n:
            continue
        if preferred is not None and d["_api"] != preferred:
            continue
        out.append(d)
    return out


def _norm(name: str) -> str:
    return "".join(ch for ch in name.lower() if ch.isalnum())


def siblings(target: dict, inputs: "list[dict]") -> "dict[str, dict]":
    """The same physical mic under each host API, matched by name.

    MME truncates names to 31 characters, so match on a shared prefix.
    """
    key = _norm(target["name"])[:20]
    found: "dict[str, dict]" = {}
    for d in inputs:
        if d["_api"] in found or "WDM-KS" in d["_api"]:
            continue   # WDM-KS can grab the device exclusively and starve the other streams
        n = _norm(d["name"])
        if n.startswith(key) or key.startswith(n[:20]):
            found[d["_api"]] = d
    found[target["_api"]] = target
    return found


# ── Recording ────────────────────────────────────────────────────────────────

class Capture:
    def __init__(self, label: str, dev: dict, channels: int, rate: int, blocksize: int | None):
        self.label, self.dev, self.channels, self.rate = label, dev, channels, rate
        self.blocksize = blocksize
        self.blocks: "list[np.ndarray]" = []
        self.error: str | None = None
        self.status_flags = 0
        self.stream: sd.InputStream | None = None
        self.live_db = -np.inf
        self._lock = threading.Lock()

    def _cb(self, indata, frames, t, status):
        if status:
            self.status_flags += 1
        block = indata.copy()
        with self._lock:
            self.blocks.append(block)
        rms = float(np.sqrt(np.mean(block.astype(np.float64) ** 2)))
        self.live_db = 20 * np.log10(rms) if rms > 0 else -np.inf

    def open(self) -> None:
        try:
            kw = dict(device=int(self.dev["index"]), channels=self.channels,
                      samplerate=self.rate, dtype=np.float32, callback=self._cb)
            if self.blocksize:
                kw["blocksize"] = self.blocksize
            self.stream = sd.InputStream(**kw)
            self.stream.start()
            self.rate = int(self.stream.samplerate)
        except Exception as exc:   # record and carry on with the other configurations
            self.error = f"{type(exc).__name__}: {exc}"
            self.stream = None

    def close(self) -> None:
        if self.stream is not None:
            try:
                self.stream.stop()
                self.stream.close()
            except Exception:
                pass

    def data(self) -> np.ndarray:
        with self._lock:
            if not self.blocks:
                return np.zeros((0, self.channels), dtype=np.float32)
            return np.concatenate(self.blocks, axis=0)


def build_captures(target: dict, inputs: "list[dict]") -> "list[Capture]":
    sib = siblings(target, inputs)
    caps = []
    rate = int(target["default_samplerate"])
    caps.append(Capture("gtap", target, 1, rate, CHUNK))
    for api, short in (("Windows WASAPI", "wasapi"), ("MME", "mme"), ("Windows DirectSound", "dsound"),
                       ("Core Audio", "coreaudio"), ("ALSA", "alsa")):
        d = sib.get(api)
        if d is None:
            continue
        ch = int(d["max_input_channels"])
        if d is target and ch == 1:
            continue   # identical to the gtap stream
        caps.append(Capture(f"{short}-{ch}ch", d, ch, int(d["default_samplerate"]), None))
    return caps


# ── Analysis ─────────────────────────────────────────────────────────────────

def db(x: float) -> float:
    return 20 * np.log10(x) if x > 0 else -np.inf


def fmt_db(x: float) -> str:
    return "  -inf" if not np.isfinite(x) else f"{x:6.1f}"


def chunk_rms_db(sig: np.ndarray) -> np.ndarray:
    n = len(sig) // CHUNK
    if n == 0:
        return np.array([-np.inf])
    c = sig[: n * CHUNK].astype(np.float64).reshape(n, CHUNK)
    r = np.sqrt(np.mean(c ** 2, axis=1))
    with np.errstate(divide="ignore"):
        return 20 * np.log10(r)


def channel_stats(sig: np.ndarray, rate: int) -> dict:
    lv = chunk_rms_db(sig)
    quiet = int(QUIET_SECONDS * rate) // CHUNK
    floor = float(np.median(lv[:quiet])) if quiet > 0 and len(lv) > quiet else float(np.median(lv))
    return {
        "peak": db(float(np.max(np.abs(sig))) if len(sig) else 0.0),
        "max_chunk": float(np.max(lv)),
        "floor": floor,
        "zeros": bool(len(sig) and not np.any(sig)),
    }


def analyse(cap: Capture) -> "list[str]":
    lines = [f"[{cap.label}]  {cap.dev['_api']}  #{cap.dev['index']}  \"{cap.dev['name']}\""]
    if cap.error:
        return lines + [f"    could not open: {cap.error}", ""]
    x = cap.data()
    lines.append(f"    opened {cap.channels} ch @ {cap.rate} Hz, {len(x) / max(cap.rate, 1):.1f} s recorded, "
                 f"{cap.status_flags} overflow/status callbacks")
    lines.append("                       peak   loudest chunk RMS   noise floor   tap above floor")
    cols = [(f"ch{i + 1}", x[:, i]) for i in range(x.shape[1])]
    if x.shape[1] > 1:
        cols.append(("mono avg", x.mean(axis=1)))   # what a 1-channel open would deliver
    for name, sig in cols:
        s = channel_stats(sig, cap.rate)
        note = "   ALL ZEROS (mic blocked / privacy setting?)" if s["zeros"] else ""
        lines.append(f"    {name:<10}      {fmt_db(s['peak'])} dB      {fmt_db(s['max_chunk'])} dB"
                     f"         {fmt_db(s['floor'])} dB      {fmt_db(s['max_chunk'] - s['floor'])} dB{note}")
    if x.shape[1] > 1 and len(x):
        a, b = x[:, 0].astype(np.float64), x[:, 1].astype(np.float64)
        i = int(np.argmax(chunk_rms_db(np.abs(a) + np.abs(b))))   # loudest chunk, per the raw channels
        lo, hi = max(0, (i - 4) * CHUNK), (i + 12) * CHUNK         # a window around the loudest tap
        def corr(u, v):
            su, sv = np.std(u), np.std(v)
            return float(np.mean((u - u.mean()) * (v - v.mean())) / (su * sv)) if su > 0 and sv > 0 else float("nan")
        c_all, c_tap = corr(a, b), corr(a[lo:hi], b[lo:hi])
        lines.append(f"    ch1/ch2 correlation: whole recording {c_all:+.2f}, around loudest tap {c_tap:+.2f}")
        if c_tap < -0.5:
            lines.append("    >>> ch1 and ch2 are PHASE-INVERTED: averaging to mono cancels the tap.")
        elif np.isfinite(c_tap) and abs(c_tap) < 0.3:
            lines.append("    >>> ch1 and ch2 carry largely different signals.")
    return lines + [""]


def verdict(caps: "list[Capture]") -> "list[str]":
    g = next((c for c in caps if c.label == "gtap"), None)
    if g is None or g.error:
        return ["Guitar Tap's configuration could not be opened — see its error above."]
    gs = channel_stats(g.data()[:, 0], g.rate)
    out = [f"Guitar Tap-style stream: loudest chunk {fmt_db(gs['max_chunk'])} dB "
           f"(Threshold slider bottom is {GTAP_MIN_THRESHOLD_DB:.0f} dB)."]
    best = None
    for c in caps:
        if c is g or c.error:
            continue
        x = c.data()
        for i in range(x.shape[1]):
            m = channel_stats(x[:, i], c.rate)["max_chunk"]
            if best is None or m > best[0]:
                best = (m, f"{c.label} ch{i + 1}")
    if best is not None:
        diff = best[0] - gs["max_chunk"]
        vs = f" ({diff:+.1f} dB vs Guitar Tap-style)" if np.isfinite(diff) else ""
        out.append(f"Loudest other configuration: {best[1]} at {fmt_db(best[0])} dB{vs}.")
    return out


# ── Output ───────────────────────────────────────────────────────────────────

def write_wav_float(path: str, data: np.ndarray, rate: int) -> None:
    """32-bit float WAV (format 3) — the stdlib wave module only writes integer PCM."""
    data = np.ascontiguousarray(data, dtype="<f4")
    ch = data.shape[1] if data.ndim == 2 else 1
    payload = data.tobytes()
    with open(path, "wb") as f:
        f.write(b"RIFF" + struct.pack("<I", 36 + len(payload)) + b"WAVE")
        f.write(b"fmt " + struct.pack("<IHHIIHH", 16, 3, ch, rate, rate * ch * 4, ch * 4, 32))
        f.write(b"data" + struct.pack("<I", len(payload)) + payload)


def environment_lines() -> "list[str]":
    lib = getattr(sd, "_libname", "?")
    return [
        f"Guitar Tap Mic Probe {PROBE_VERSION}   {_dt.datetime.now().isoformat(timespec='seconds')}",
        f"OS:           {platform.platform()}",
        f"Python:       {sys.version.split()[0]} ({platform.architecture()[0]})",
        f"sounddevice:  {sd.__version__}   PortAudio: {sd.get_portaudio_version()[1]}   lib: {lib}",
        f"numpy:        {np.__version__}",
    ]


def device_table(inputs: "list[dict]") -> "list[str]":
    try:
        default_in = sd.default.device[0]
    except Exception:
        default_in = None
    lines = ["All input devices (index / host API / channels / default rate / name):"]
    for d in inputs:
        mark = "*" if d["index"] == default_in else " "
        lines.append(f"  {mark}{d['index']:>3}  {d['_api']:<20} {int(d['max_input_channels']):>2} ch  "
                     f"{int(d['default_samplerate']):>6} Hz  {d['name']}")
    lines.append("  (* = PortAudio default input)")
    return lines


def desktop() -> str:
    d = os.path.join(os.path.expanduser("~"), "Desktop")
    return d if os.path.isdir(d) else os.path.expanduser("~")


def pause_exit(code: int, prompt: bool) -> int:
    if prompt:
        try:
            input("\nPress Enter to close this window...")
        except EOFError:
            pass
    return code


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--list", action="store_true", help="list input devices and exit")
    ap.add_argument("--device", type=int, help="PortAudio index of the mic (skips the menu)")
    ap.add_argument("--seconds", type=float, default=25.0, help="recording length (default 25)")
    ap.add_argument("--outdir", help="where to write results (default: Desktop)")
    ap.add_argument("--yes", action="store_true", help="no prompts (for scripted runs)")
    args = ap.parse_args()
    prompt = not args.yes

    env = environment_lines()
    inputs = all_inputs()
    print("\n".join(env) + "\n")
    print("\n".join(device_table(inputs)) + "\n")
    if args.list:
        return 0

    choices = gtap_device_list(inputs)
    if args.device is not None:
        target = next((d for d in inputs if d["index"] == args.device), None)
        if target is None:
            print(f"No input device with index {args.device}.")
            return pause_exit(2, prompt)
    else:
        if not choices:
            print("No microphones found.")
            return pause_exit(2, prompt)
        print("Microphones as Guitar Tap lists them:")
        for i, d in enumerate(choices, 1):
            print(f"  {i}. {d['name']}")
        while True:
            s = input(f"\nType the number of the microphone to test (1-{len(choices)}) and press Enter: ").strip()
            if s.isdigit() and 1 <= int(s) <= len(choices):
                target = choices[int(s) - 1]
                break

    caps = build_captures(target, inputs)
    print("\nWill record these at the same time:")
    for c in caps:
        print(f"  {c.label:<12} {c.dev['_api']:<20} #{c.dev['index']:<3} {c.channels} ch  {c.dev['name']}")

    if prompt:
        print("\nWhen you press Enter the recording starts and lasts "
              f"{args.seconds:.0f} seconds:\n"
              f"  * the first {QUIET_SECONDS:.0f} seconds: stay QUIET (this measures background noise)\n"
              "  * then TAP the guitar 5 or 6 times, a couple of seconds apart,\n"
              "    the same way you would when using Guitar Tap.\n"
              "If Audacity is recording the same microphone at the same time, that's fine.")
        input("\nPress Enter to start...")

    for c in caps:
        c.open()
    t0 = time.time()
    try:
        while (el := time.time() - t0) < args.seconds:
            phase = "QUIET " if el < QUIET_SECONDS else "TAP NOW"
            meters = "  ".join(f"{c.label}:{fmt_db(c.live_db)}" for c in caps if not c.error)
            print(f"\r  {phase}  {args.seconds - el:4.0f}s left   {meters}   ", end="", flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        print("\n  stopped early")
    finally:
        for c in caps:
            c.close()
    print("\n")

    stamp = _dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out = os.path.join(args.outdir or desktop(), f"GuitarTap-MicProbe-{stamp}")
    os.makedirs(out, exist_ok=True)

    report = env + ["", f"Tested: #{target['index']} {target['_api']} \"{target['name']}\"", ""]
    report += ["Verdict:"] + ["  " + v for v in verdict(caps)] + [""]
    for c in caps:
        report += analyse(c)
        if not c.error:
            write_wav_float(os.path.join(out, f"{c.label}.wav"), c.data(), c.rate)
    report += device_table(inputs)
    text = "\n".join(report) + "\n"
    with open(os.path.join(out, "report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text)

    zpath = out + ".zip"
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for n in sorted(os.listdir(out)):
            z.write(os.path.join(out, n), arcname=os.path.join(os.path.basename(out), n))
    print(f"Results saved to:\n  {zpath}\nPlease email that .zip file back. Thank you!")
    if prompt and platform.system() == "Windows":
        try:
            os.startfile(os.path.dirname(zpath))   # type: ignore[attr-defined]
        except Exception:
            pass
    return pause_exit(0, prompt)


if __name__ == "__main__":
    sys.exit(main())
