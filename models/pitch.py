"""
Equal-temperament pitch analysis — mirrors Swift Pitch.swift.

Provides note detection, cents deviation, and frequency conversion for
the 12-tone equal-temperament (12-TET) system where all semitones are
equal-ratio intervals of 2^(1/12).  The reference pitch for the entire
scale is A4 (configurable; defaults to 440 Hz).

Algorithm Overview:
  1. C0 anchor — C0 is derived from A4 by shifting 4 octaves down and 9 semitones down:
     f_C0 = f_A4 × 2^(−4.75).
  2. Half-steps from C0 — Any frequency maps to a half-step count via
     h = round(12 × log₂(f / f_C0)).
  3. Note and octave — octave = h / 12, note = h % 12 (0 = C, 1 = C#, … 11 = B).
  4. Frequency of a note — f(note, octave) = f_C0 × 2^(note/12) × 2^octave.
  5. Cents deviation — cents = 1200 × log₂(f_measured / f_nearest_note).

Reference: https://www.johndcook.com/blog/2016/02/10/musical-pitch-notation/
"""

from math import log2, pow as mpow


class Pitch:
    """Provides equal-temperament pitch calculations: note detection, cents deviation,
    frequency-of-note lookup, and range queries.

    All calculations assume the 12-tone equal-temperament scale anchored at a4.
    Create one shared instance per application context; there is no meaningful state
    other than the A4 reference frequency.

    Mirrors Swift Pitch class (Pitch.swift).
    """

    # MARK: - Properties

    # Note name strings in ascending chromatic order, index 0 = C through index 11 = B.
    # (Python class attribute — matches Swift private let noteNames)
    _note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    # MARK: - Initialization

    def __init__(self, a4: float = 440.0) -> None:
        """Create a Pitch calculator with the given A4 reference frequency.

        - Parameter a4: Reference frequency of A4, in Hz.  Defaults to the standard 440 Hz.

        Mirrors Swift Pitch.init(a4:).
        """
        # The reference frequency of A4, in Hz.
        # The standard concert pitch is 440 Hz.  Change this value to support alternative
        # tuning systems (e.g. 432 Hz historical pitch or 415 Hz baroque pitch).
        # Mirrors Swift Pitch.a4.
        self.a4: float = a4

    @property
    def c0(self) -> float:
        """The derived frequency of C0, computed from a4.

        C0 is 4 octaves and 9 semitones (= 57 semitones) below A4:
        f_C0 = f_A4 × 2^(−4.75).
        All note-frequency calculations use C0 as their base reference.

        Mirrors Swift Pitch.c0.
        """
        # -4.75 octaves = -4 octaves (4 × 12 semitones) minus 9 semitones = -57 semitones
        return self.a4 * mpow(2, -4.75)

    # MARK: - Pitch Calculation

    def pitch(self, frequency: float) -> tuple[int, int]:
        """Return the note index (0–11) and octave number closest to the given frequency.

        The note index maps as: 0 = C, 1 = C#, 2 = D, 3 = D#, 4 = E, 5 = F,
        6 = F#, 7 = G, 8 = G#, 9 = A, 10 = A#, 11 = B.

        - Parameter frequency: The frequency to analyse, in Hz.
        - Returns: A tuple (note, octave) identifying the nearest equal-temperament pitch.

        Mirrors Swift Pitch.pitch(frequency:).
        """
        # Count half-steps above C0; rounding snaps to the nearest semitone.
        half_steps = int(round(12 * log2(frequency / self.c0)))
        octave = half_steps // 12
        note = half_steps % 12
        return note, octave

    def pitch_range(self, frequency: float) -> tuple[float, float]:
        """Return the frequencies of the notes immediately above and below the given frequency.

        - Parameter frequency: The frequency to analyse, in Hz.
        - Returns: A tuple (upper, lower) where upper is the frequency of the next semitone
          above the nearest note and lower is the semitone below.
          Octave boundaries are handled correctly (e.g. B4 → C5 above, A4 below).

        Mirrors Swift Pitch.pitchRange(frequency:).
        """
        note, octave = self.pitch(frequency)
        c = self.cents(frequency)

        if c >= 0:
            # Frequency is above the nearest note: upper bound is the next semitone.
            if note == 11:
                upper = self.freq(note=0, octave=octave + 1)  # B → C in next octave
            else:
                upper = self.freq(note=note + 1, octave=octave)
            lower = self.freq(note=note, octave=octave)
        else:
            # Frequency is below the nearest note: lower bound is the previous semitone.
            upper = self.freq(note=note, octave=octave)
            if note == 0:
                lower = self.freq(note=11, octave=octave - 1)  # C → B in previous octave
            else:
                lower = self.freq(note=note - 1, octave=octave)

        return upper, lower

    def note(self, frequency: float) -> str:
        """Return the name of the nearest equal-temperament note for the given frequency.

        - Parameter frequency: The frequency to analyse, in Hz.
        - Returns: A string such as "A4" or "C#3".

        Mirrors Swift Pitch.note(frequency:).
        """
        n, octave = self.pitch(frequency)
        return f"{self._note_names[n]}{octave}"

    def freq0(self, frequency: float) -> float:
        """Return the frequency of the nearest equal-temperament note for the given frequency.

        Useful for computing how far (in Hz) the measured frequency deviates from the ideal
        note frequency.

        - Parameter frequency: The frequency to analyse, in Hz.
        - Returns: The exact frequency in Hz of the nearest note.

        Mirrors Swift Pitch.freq0(frequency:).
        """
        n, octave = self.pitch(frequency)
        return self.freq(note=n, octave=octave)

    def freq(self, note: int, octave: int) -> float:
        """Return the exact frequency for a note specified by index and octave.

        Formula: f = f_C0 × 2^(note/12) × 2^octave

        - Parameters:
          - note: Chromatic note index (0 = C, 1 = C#, … 11 = B).
          - octave: Octave number (4 is the standard middle-C octave for octave 4 at C4 ≈ 261 Hz).
        - Returns: Frequency in Hz.

        Mirrors Swift Pitch.freq(note:octave:).
        """
        return mpow(2, note / 12.0) * self.c0 * mpow(2, octave)

    def cents(self, frequency: float) -> float:
        """Return the signed cents offset from the nearest equal-temperament pitch.

        Formula: cents = 1200 × log₂(f_measured / f_nearest)

        - Parameter frequency: The measured frequency, in Hz.
        - Returns: Cents offset in the range −50 to +50 (100 cents = 1 semitone).
          Negative means flat; positive means sharp.

        Mirrors Swift Pitch.cents(frequency:).
        """
        n, octave = self.pitch(frequency)
        f0 = self.freq(note=n, octave=octave)
        # 1200 × log₂ gives the interval in cents between f0 (ideal) and frequency (measured).
        return 1200 * log2(frequency / f0)

    # MARK: - Convenience Extensions

    def formatted_note(self, frequency: float) -> str:
        """Return a formatted string combining the nearest note name and its cents offset.

        Example output: "A4 (+23 cents)" or "C#3 (-5 cents)".

        - Parameter frequency: The frequency to format, in Hz.
        - Returns: A human-readable pitch-and-deviation string.

        Mirrors Swift Pitch.formattedNote(frequency:).
        """
        note_str = self.note(frequency)
        c = self.cents(frequency)
        sign = "+" if c >= 0 else ""
        return f"{note_str} ({sign}{c:.0f} cents)"

    def is_in_tune(self, frequency: float, threshold: float = 10.0) -> bool:
        """Return True if the frequency is within *threshold* cents of any pitch.

        - Parameters:
          - frequency: The frequency to check, in Hz.
          - threshold: Maximum absolute cents deviation considered "in tune".  Defaults to 10 cents.
        - Returns: True when |cents| ≤ threshold.

        Mirrors Swift Pitch.isInTune(frequency:threshold:).
        """
        return abs(self.cents(frequency)) <= threshold


# MARK: - Debug / Testing

def run_example() -> None:
    """Run a set of sample pitch calculations and print results to the console.

    Useful for verifying that the equal-temperament formula produces expected values.

    Mirrors Swift Pitch.runExample() (DEBUG-only static function in Pitch.swift).
    """
    pitch = Pitch(a4=440)

    print("Example 1:")
    f1: float = 173
    print(f"f_1 = {f1}")
    print(f"Note = {pitch.note(f1)}")
    print(f"f_0 = {pitch.freq0(f1)}")
    print(f"cents = {pitch.cents(f1)}")
    print("==========================")

    print("Example 2:")
    f2: float = 175.8
    print(f"f_1 = {f2}")
    print(f"Note = {pitch.note(f2)}")
    print(f"f_0 = {pitch.freq0(f2)}")
    print(f"cents = {pitch.cents(f2)}")
    print(f"formatted = {pitch.formatted_note(f2)}")
    print(f"in tune? {pitch.is_in_tune(f2)}")


if __name__ == "__main__":
    run_example()
