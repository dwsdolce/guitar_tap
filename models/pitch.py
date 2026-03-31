"""
Equal-temperament pitch analysis — mirrors Swift Pitch.swift.

For a specified frequency find the pitch, octave, and cents offset.
This is based on the specified setting for A4.
There are also some utilities for formatting the name and the
closest frequency of a note.
Some of these calculations come from:
    https://www.johndcook.com/blog/2016/02/10/musical-pitch-notation/
"""

from math import log2


class Pitch:
    """Construct an object based on a specified frequency for A4.

    Mirrors Swift Pitch class (Pitch.swift).
    Provides methods to return pitch, octave, cents, and frequency of
    the closest note.
    """

    a4 = 440
    c_0 = a4 * pow(2, -4.75)  # -4 octaves below A4 and -9/12 below A
    note_names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    def __init__(self, a4: int) -> None:
        self.a4 = a4
        self.c_0 = a4 * pow(2, -4.75)  # -4 octaves below A4 and -9/12 below A

    def pitch(self, frequency: float) -> tuple[int, int]:
        """Find the pitch (note index and octave) closest to this frequency.

        Mirrors Swift Pitch.pitch(frequency:).
        """
        half_steps = round(12 * log2(frequency / self.c_0))
        octave = half_steps // 12
        note = half_steps % 12
        return note, octave

    def pitch_range(self, frequency: float) -> tuple[float, float]:
        """Return the frequencies of the upper and lower adjacent notes.

        Mirrors Swift Pitch.pitchRange(frequency:).
        """
        note, octave = self.pitch(frequency)
        cents = self.cents(frequency)
        if cents >= 0:
            upper_note = self.freq(note + 1, octave)
            lower_note = self.freq(note, octave)
            if note == 11:
                upper_note = self.freq(0, octave + 1)
        else:
            upper_note = self.freq(note, octave)
            lower_note = self.freq(note - 1, octave)
            if note == 0:
                lower_note = self.freq(11, octave - 1)
        return upper_note, lower_note

    def note(self, frequency: float) -> str:
        """Return a string of the pitch closest to this frequency.

        Mirrors Swift Pitch.note(frequency:) → String.
        """
        note, octave = self.pitch(frequency)
        return f"{self.note_names[note]}{octave}"

    def freq0(self, frequency: float) -> float:
        """Return the ideal frequency of the pitch closest to this frequency.

        Mirrors Swift Pitch.freq0(frequency:).
        """
        note, octave = self.pitch(frequency)
        return self.freq(note, octave)

    def freq(self, pitch: float, octave: int) -> float:
        """Return the frequency of the note specified by pitch index and octave.

        Mirrors Swift Pitch.freq(note:octave:).
        """
        return 2 ** (pitch / 12) * self.c_0 * pow(2, octave)

    def cents(self, frequency: float) -> float:
        """Return the cents deviation from the nearest pitch.

        Mirrors Swift Pitch.cents(frequency:).
        """
        note, octave = self.pitch(frequency)
        f_0 = self.freq(note, octave)
        return 1200 * log2(frequency / f_0)

    def formatted_note(self, frequency: float) -> str:
        """Return a formatted string combining note name and cents deviation.

        Mirrors Swift Pitch.formattedNote(frequency:).
        """
        note_str = self.note(frequency)
        c = self.cents(frequency)
        return f"{note_str} {c:+.0f}¢"

    def is_in_tune(self, frequency: float, threshold: float = 10.0) -> bool:
        """Return True if the frequency is within *threshold* cents of any pitch.

        Mirrors Swift Pitch.isInTune(frequency:threshold:).
        """
        return abs(self.cents(frequency)) <= threshold


if __name__ == "__main__":
    t_pitch = Pitch(440)

    F1 = 173
    print(f"frequency = {F1}")
    print(f"note = {t_pitch.note(F1)}")
    print(f"freq0 = {t_pitch.freq0(F1)}")
    print(f"cents = {t_pitch.cents(F1)}")
    print("==========================")
    F1 = 175.8
    print(f"frequency = {F1}")
    print(f"note = {t_pitch.note(F1)}")
    print(f"freq0 = {t_pitch.freq0(F1)}")
    print(f"cents = {t_pitch.cents(F1)}")
