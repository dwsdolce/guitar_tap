import numpy as np
import sounddevice as sd

import matplotlib.pyplot as plt

# Parameters
duration = 3  # seconds to record
fs = 44100    # sample rate

print("Recording...")
audio = sd.rec(int(duration * fs), samplerate=fs, channels=1, dtype='float64')
sd.wait()
print("Recording complete.")

# Flatten audio to 1D
audio = audio.flatten()

# FFT
n = len(audio)
freqs = np.fft.rfftfreq(n, d=1/fs)
fft_vals = np.abs(np.fft.rfft(audio))

# Plot
plt.figure(figsize=(10, 6))
plt.plot(freqs, fft_vals)
plt.title('Frequency Response of Microphone Audio')
plt.xlabel('Frequency (Hz)')
plt.ylabel('Amplitude')
plt.xlim(0, fs // 2)
plt.grid(True)
plt.show()