"""
    For a specified frequency find the pitch, octave, and cents offset.
    This is based on the specified setting for A4.
    There are also some utilities for formatting the name and the
    closest frequency of a note.
    Some of these calculations come from:
        https://www.johndcook.com/blog/2016/02/10/musical-pitch-notation/
"""
from math import log2

class Pitch():
    """ Construct an object based on a specified frequency for A4.
        Provide methods to return pitch, octave, cents, and frequncy of
        closest note.
    """

    a_4 = 440
    c_0 = a_4*pow(2, -4.75) # -4 octaves below A4 and -9/12 below A
    name = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

    def __init__(self, a_4: int) -> None:
        self.a_4 = a_4
        self.c_0 = a_4*pow(2, -4.75) # -4 octaves below A4 and -9/12 below A

    def pitch(self, f_1: float) -> tuple[int, int]:
        """ Find the pitch (i.e. note and octave closest to this frequency """
        # This gives the 1/2 steps above c_0
        half_steps = round(12*log2(f_1/self.c_0))
        octave = half_steps // 12
        note = half_steps % 12
        return note, octave

    def note(self, f_1: float) -> str:
        """ Return a string of the pitch closest to this frequency """
        note, octave = self.pitch(f_1)
        return f'{self.name[note]}{octave}'

    def freq0(self, f_1: float) -> float:
        """ Return the frequency of the pitch closest to this frequency """
        note, octave = self.pitch(f_1)
        f_0 = self.freq(note, octave)
        return f_0

    def freq(self, pitch: float, octave:int) -> float:
        """ Return the frequency of the note specified by pitch and octave """
        freq = 2**(pitch/12) * self.c_0 * pow(2, octave) # need to correct for active
        return freq

    def cents(self, f_1: float) -> float:
        """ Return the cents from the pitch closest to this frequency """
        note, octave = self.pitch(f_1)
        f_0 = self.freq(note, octave)
        cents = 1200 * log2(f_1/f_0) # f0 is the desired frequency and f is the actual

        return cents

if __name__ == "__main__":
    t_pitch = Pitch(440)

    F1 = 173
    print(f'f_1 = {F1}')
    print(f'Note = {t_pitch.note(F1)}')
    print(f'f_0 = {t_pitch.freq0(F1)}')
    print(f'cents = {t_pitch.cents(F1)}')
    print('==========================')
    F1 = 175.8
    print(f'f_1 = {F1}')
    print(f'Note = {t_pitch.note(F1)}')
    print(f'f_0 = {t_pitch.freq0(F1)}')
    print(f'cents = {t_pitch.cents(F1)}')
