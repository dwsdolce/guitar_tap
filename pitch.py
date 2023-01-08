# https://www.johndcook.com/blog/2016/02/10/musical-pitch-notation/

from math import log2, pow

class Pitch():

    A4 = 440
    C0 = A4*pow(2, -4.75) # -4 octaves below A4 and -9/12 below A
    name = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    
    def __init__(self, A4):
        self.A4 = A4
        self.C0 = A4*pow(2, -4.75) # -4 octaves below A4 and -9/12 below A

    def pitch(self, f1):
        # This gives the 1/2 steps above C0
        half_steps = round(12*log2(f1/self.C0))
        octave = half_steps // 12
        note = half_steps % 12
        return note, octave

    def note(self, f1):
        note, octave = self.pitch(f1)
        return f'{self.name[note]}{octave}'

    def freq0(self, f1):
        n0, octave = self.pitch(f1)
        f0 = self.freq(n0, octave)
        return f0

    def freq(self, pitch, octave):
        f = 2**(pitch/12) * self.C0 * pow(2, octave) # need to correct for active
        return f

    def cents(self, f1):
        n0, octave = self.pitch(f1)
        f0 = self.freq(n0, octave)
        cents = 1200 * log2(f1/f0) # f0 is the desired frequency and f is the actual

        return cents

if __name__ == "__main__":
    pitch = Pitch(440)

    f1 = 173
    print(f'f1 = {f1}')
    print(f'Note = {pitch.note(f1)}')
    print(f'f0 = {pitch.freq0(f1)}')
    print(f'cents = {pitch.cents(f1)}')
    print('==========================')
    f1 = 175.8
    print(f'f1 = {f1}')
    print(f'Note = {pitch.note(f1)}')
    print(f'f0 = {pitch.freq0(f1)}')
    print(f'cents = {pitch.cents(f1)}')
