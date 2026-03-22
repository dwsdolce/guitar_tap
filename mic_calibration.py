"""
    Microphone calibration support (UMIK-1 / REW .cal format).

    The .cal file format used by miniDSP UMIK-1 microphones and REW
    (Room EQ Wizard) consists of optional header lines (starting with
    '"' or '*') followed by whitespace-separated (freq_hz, db_correction)
    pairs, one per line.

    Example:
        "UMIK-1 Calibration Data"
        * Serial Number: 1234567
        * Sensitivity @ 94dB SPL: -35.00 dBFS
        20.0    0.12
        25.0   -0.05
        ...
        20000.0  1.43
"""

import re
import numpy as np
import numpy.typing as npt


_SENS_RE = re.compile(r"([-+]?\d+\.?\d*)\s*dB", re.IGNORECASE)


def parse_cal_metadata(path: str) -> dict:
    """Return metadata from a calibration file without loading correction data.

    Returns a dict with keys:
      'sensitivity_db' : float | None  — from header (e.g. "Sens Factor = -18.39 dB")
      'data_points'    : int           — number of frequency/correction pairs
      'freq_min'       : float | None  — lowest frequency in the file
      'freq_max'       : float | None  — highest frequency in the file
    """
    sensitivity: float | None = None
    data_points = 0
    freq_min: float | None = None
    freq_max: float | None = None

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line:
                continue
            if line.startswith('"') or line.startswith("*"):
                lower = line.lower()
                if "sens" in lower:
                    m = _SENS_RE.search(line)
                    if m:
                        sensitivity = float(m.group(1))
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                freq = float(parts[0])
                float(parts[1])
                if freq > 0:
                    data_points += 1
                    if freq_min is None or freq < freq_min:
                        freq_min = freq
                    if freq_max is None or freq > freq_max:
                        freq_max = freq
            except ValueError:
                continue

    return {
        "sensitivity_db": sensitivity,
        "data_points": data_points,
        "freq_min": freq_min,
        "freq_max": freq_max,
    }


def parse_cal_file(path: str) -> npt.NDArray[np.float64]:
    """Parse a UMIK-1/REW calibration file.

    Returns an (N, 2) float64 array: column 0 = Hz, column 1 = dB correction.
    Raises ValueError if no valid data points are found.
    """
    points: list[tuple[float, float]] = []

    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            line = raw.strip()
            if not line or line.startswith('"') or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            try:
                freq = float(parts[0])
                db   = float(parts[1])
                if freq > 0:
                    points.append((freq, db))
            except ValueError:
                continue  # header text or malformed line

    if not points:
        raise ValueError(f"No calibration data found in '{path}'")

    arr = np.array(points, dtype=np.float64)
    # Sort by frequency (required by np.interp)
    arr = arr[arr[:, 0].argsort()]
    return arr


def interpolate_to_bins(
    cal_data: npt.NDArray[np.float64],
    bin_freqs: npt.NDArray[np.float64],
) -> npt.NDArray[np.float64]:
    """Interpolate calibration corrections onto FFT bin frequencies.

    Frequencies below/above the calibration range are clamped to 0 dB
    (no correction applied outside the measured range).

    Returns a 1-D array of dB corrections, same length as *bin_freqs*.
    """
    return np.interp(
        bin_freqs,
        cal_data[:, 0],
        cal_data[:, 1],
        left=0.0,
        right=0.0,
    )
