"""Live Audio Waveform Visualization using sounddevice and matplotlib."""
import sounddevice as sd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.animation as animation

# Parameters
SAMPLERATE = 44100  # Sample rate in Hz
DURATION = 0.1      # Duration of each audio chunk in seconds
FRAMES_PER_BUFFER = int(SAMPLERATE * DURATION)

# Create a figure and axis for plotting
fig, ax = plt.subplots()
x = np.arange(FRAMES_PER_BUFFER)
line, = ax.plot(x, np.zeros(FRAMES_PER_BUFFER))
ax.set_ylim(-1, 1)
ax.set_xlim(0, FRAMES_PER_BUFFER)
ax.set_title("Live Audio Waveform")
ax.set_xlabel("Samples")
ax.set_ylabel("Amplitude")

# Audio callback function

def audio_callback(indata, _frames, _time, status):
    """Callback function to process audio input."""
    if status:
        print(status)
    line.set_ydata(indata[:, 0])  # Update waveform with new audio data

# Animation update function


def update(_frame):
    """Update function for animation."""
    return line,


# Start audio stream
stream = sd.InputStream(callback=audio_callback, channels=1,
                        samplerate=SAMPLERATE, blocksize=FRAMES_PER_BUFFER, dtype=np.float32)
with stream:
    ani = animation.FuncAnimation(
        fig, update, cache_frame_data=False, interval=DURATION * 1000, blit=True)
    plt.show()
