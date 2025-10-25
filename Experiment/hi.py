import numpy as np
import sounddevice as sd

import scipy.signal

def record_audio(duration=2, fs=44100):
    print("Recording...")
    audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='float32')
    sd.wait()
    print("Recording finished.")
    return audio.flatten(), fs

def detect_pitch(audio, fs):
    # Autocorrelation method
    audio = audio - np.mean(audio)
    corr = np.correlate(audio, audio, mode='full')
    print(f'corr = {corr}')
    print(f'len(corr) = {len(corr)}')
    corr = corr[len(corr)//2:]
    d = np.diff(corr)
    print(f'd = {d}')
    print(f'len(d) = {len(d)}')
    start = np.where(d > 0)[0][0]
    peak = np.argmax(corr[start:]) + start
    print(f'peak = {peak}')
    if peak == 0:
        return 0
    pitch = fs / peak
    return pitch

if __name__ == "__main__":
    audio, fs = record_audio()
    pitch = detect_pitch(audio, fs)
    if pitch > 0:
        print(f"Estimated pitch: {pitch:.2f} Hz")
    else:
        print("Could not detect pitch.")