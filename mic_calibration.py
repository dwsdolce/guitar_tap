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

import numpy as np
import numpy.typing as npt


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
