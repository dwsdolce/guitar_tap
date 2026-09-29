# @parity none - Windows-only diagnostic. The macOS monitor uses CoreAudio property
# listeners and Linux uses udev, so there is no counterpart to mirror.
"""Probe: does IMMNotificationClient fire at the moment PortAudio can see the device?

Standalone - touches nothing in the app. It answers the two questions the #21 Windows
step-2 failure turns on:

  1. Does an audio ENDPOINT event fire on plug-in (as opposed to the USB device-interface
     arrival that CM_Register_Notification reports, which is what fires too early)?
  2. At the instant that event arrives, does a fresh Pa_Terminate/Pa_Initialize enumerate
     the new microphone? If yes, the endpoint event needs no settle delay, because
     PortAudio's WASAPI host API reads the very list that just changed.

Run from the REPO ROOT (it imports the app's device filter from src/), then plug a USB
mic in, wait, unplug it. Ctrl-C to stop.

    .venv/Scripts/python.exe -u Tooling/mmdevice-probe.py

It answered #21 step 2 on Windows; the measurements and what they settled are written up
in the hub as MIC-SELECTION.md item 19. Keep it for the next Windows machine: whether an
endpoint event coincides with PortAudio seeing the device is a per-machine question, and
this is what answers it without touching the app.

v2: the callbacks now print IMMEDIATELY and do no work of their own - they put the event
on a queue for the main thread. v1 re-initialised PortAudio inside the COM callback and
printed only afterwards, so any failure in that call made the whole event invisible and
returned a failing HRESULT to Windows. The only callback that showed up was the one that
did nothing (OnPropertyValueChanged), which is the tell. Heavy work does not belong on a
COM worker thread in the app either.
"""

from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
from ctypes import POINTER, Structure, c_wchar_p

import comtypes
from comtypes import COMMETHOD, GUID, COMObject, IUnknown
from comtypes.client import CreateObject

sys.path.insert(0, "src")

CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")

# DEVICE_STATE_* from mmdeviceapi.h
_STATE = {1: "ACTIVE", 2: "DISABLED", 4: "NOTPRESENT", 8: "UNPLUGGED"}
_FLOW = {0: "render", 1: "capture", 2: "all"}
_ROLE = {0: "console", 1: "multimedia", 2: "communications"}

_t0 = time.monotonic()
_events: "queue.Queue[tuple[float, str, str]]" = queue.Queue()


def _stamp(t: float | None = None) -> str:
    return f"t={(t if t is not None else time.monotonic()) - _t0:7.3f}s"


class PROPERTYKEY(Structure):
    _fields_ = [("fmtid", GUID), ("pid", ctypes.c_ulong)]


class IMMNotificationClient(IUnknown):
    _iid_ = GUID("{7991EEC9-7E89-4D85-8390-6C703CEC60C0}")
    _methods_ = [
        COMMETHOD([], comtypes.HRESULT, "OnDeviceStateChanged",
                  (["in"], c_wchar_p, "pwstrDeviceId"),
                  (["in"], ctypes.c_ulong, "dwNewState")),
        COMMETHOD([], comtypes.HRESULT, "OnDeviceAdded",
                  (["in"], c_wchar_p, "pwstrDeviceId")),
        COMMETHOD([], comtypes.HRESULT, "OnDeviceRemoved",
                  (["in"], c_wchar_p, "pwstrDeviceId")),
        COMMETHOD([], comtypes.HRESULT, "OnDefaultDeviceChanged",
                  (["in"], ctypes.c_uint, "flow"),
                  (["in"], ctypes.c_uint, "role"),
                  (["in"], c_wchar_p, "pwstrDefaultDeviceId")),
        COMMETHOD([], comtypes.HRESULT, "OnPropertyValueChanged",
                  (["in"], c_wchar_p, "pwstrDeviceId"),
                  (["in"], PROPERTYKEY, "key")),
    ]


class IMMDeviceEnumerator(IUnknown):
    """Only the vtable slots up to the two we need; declaration order sets the offsets."""

    _iid_ = GUID("{A95664D2-9614-4F35-A746-DE8DB63617E6}")
    _methods_ = [
        COMMETHOD([], comtypes.HRESULT, "EnumAudioEndpoints",
                  (["in"], ctypes.c_uint, "dataFlow"),
                  (["in"], ctypes.c_ulong, "dwStateMask"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppDevices")),
        COMMETHOD([], comtypes.HRESULT, "GetDefaultAudioEndpoint",
                  (["in"], ctypes.c_uint, "dataFlow"),
                  (["in"], ctypes.c_uint, "role"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppEndpoint")),
        COMMETHOD([], comtypes.HRESULT, "GetDevice",
                  (["in"], c_wchar_p, "pwstrId"),
                  (["out"], POINTER(POINTER(IUnknown)), "ppDevice")),
        COMMETHOD([], comtypes.HRESULT, "RegisterEndpointNotificationCallback",
                  (["in"], POINTER(IMMNotificationClient), "pClient")),
        COMMETHOD([], comtypes.HRESULT, "UnregisterEndpointNotificationCallback",
                  (["in"], POINTER(IMMNotificationClient), "pClient")),
    ]


def portaudio_inputs() -> list[str]:
    """Re-initialise PortAudio and return the input devices the APP's filter keeps."""
    import sounddevice as sd

    from guitar_tap.models.audio_device import filter_input_devices

    try:
        sd._terminate()
    except Exception:
        pass
    sd._initialize()
    raw = list(sd.query_devices())
    try:
        apis = list(sd.query_hostapis())
        for d in raw:
            i = int(d.get("hostapi", -1))
            if 0 <= i < len(apis):
                d["_hostapi_name"] = apis[i].get("name", "")
    except Exception:
        pass
    return [d["name"] for d in filter_input_devices(raw)]


def _post(event: str, detail: str = "") -> None:
    """Called ON THE COM THREAD: timestamp, print, enqueue. No real work here."""
    t = time.monotonic()
    print(f"{_stamp(t)}  {event:<22} {detail}", flush=True)
    _events.put((t, event, detail))


class NotificationClient(COMObject):
    _com_interfaces_ = [IMMNotificationClient]

    prop_changes = 0

    def IMMNotificationClient_OnDeviceStateChanged(self, this, pwstrDeviceId, dwNewState):
        _post("OnDeviceStateChanged",
              f"state={_STATE.get(dwNewState, dwNewState)} id=...{str(pwstrDeviceId)[-22:]}")
        return 0

    def IMMNotificationClient_OnDeviceAdded(self, this, pwstrDeviceId):
        _post("OnDeviceAdded", f"id=...{str(pwstrDeviceId)[-22:]}")
        return 0

    def IMMNotificationClient_OnDeviceRemoved(self, this, pwstrDeviceId):
        _post("OnDeviceRemoved", f"id=...{str(pwstrDeviceId)[-22:]}")
        return 0

    def IMMNotificationClient_OnDefaultDeviceChanged(self, this, flow, role, pwstrDefaultDeviceId):
        _post("OnDefaultDeviceChanged",
              f"flow={_FLOW.get(flow, flow)} role={_ROLE.get(role, role)} "
              f"id=...{str(pwstrDefaultDeviceId)[-22:]}")
        return 0

    def IMMNotificationClient_OnPropertyValueChanged(self, this, pwstrDeviceId, key):
        NotificationClient.prop_changes += 1
        _post("OnPropertyValueChanged", f"pid={key.pid} id=...{str(pwstrDeviceId)[-22:]}")
        return 0


def main() -> int:
    # Register from a dedicated MTA thread. comtypes CoInitializes the importing thread as
    # an STA, and an STA callback object only receives calls while a message pump runs - a
    # console script has none. A fresh thread has no apartment yet, so it can join the MTA
    # and take callbacks directly on COM worker threads. The app's monitor needs the same.
    ready = threading.Event()
    state: dict[str, object] = {}

    def _run() -> None:
        enumerator = None
        client = None
        try:
            comtypes.CoInitializeEx(comtypes.COINIT_MULTITHREADED)
            enumerator = CreateObject(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
            client = NotificationClient()
            enumerator.RegisterEndpointNotificationCallback(client)
        except Exception as exc:  # noqa: BLE001 - probe: report and stop
            state["error"] = exc
            ready.set()
            return
        ready.set()
        while not state.get("stop"):
            time.sleep(0.2)
        try:
            enumerator.UnregisterEndpointNotificationCallback(client)
        except Exception as exc:  # noqa: BLE001
            print("unregister failed:", exc)

    t = threading.Thread(target=_run, daemon=True, name="mmdevice-probe")
    t.start()
    ready.wait(10)
    if "error" in state:
        print("registration FAILED:", state["error"])
        return 1

    print("Registered IMMNotificationClient (MTA thread).", flush=True)
    names = portaudio_inputs()
    print(f"{_stamp()}  BASELINE               PortAudio sees {len(names)}: {names}", flush=True)
    print("\nPlug the UMIK in, wait ~10 s, then unplug it. Ctrl-C to stop.\n", flush=True)

    try:
        while True:
            try:
                t_evt, event, _detail = _events.get(timeout=0.2)
            except queue.Empty:
                continue
            # Drain any burst so one enumeration answers the whole burst.
            extra = 0
            while True:
                try:
                    _events.get_nowait()
                    extra += 1
                except queue.Empty:
                    break
            try:
                names = portaudio_inputs()
                umik = any("umik" in n.lower() for n in names)
                lag = time.monotonic() - t_evt
                print(f"{'':11}   -> after {event}"
                      f"{f' (+{extra} more)' if extra else ''}, {lag * 1000:.0f} ms later: "
                      f"PortAudio sees {len(names)}, UMIK {'YES' if umik else 'no'}", flush=True)
                print(f"{'':14}  {names}", flush=True)
            except Exception as exc:  # noqa: BLE001
                print(f"{'':11}   -> enumeration FAILED: {type(exc).__name__}: {exc}", flush=True)
    except KeyboardInterrupt:
        print(f"\n{_stamp()}  stopping ({NotificationClient.prop_changes} property changes seen)")
    finally:
        state["stop"] = True
        t.join(timeout=2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
