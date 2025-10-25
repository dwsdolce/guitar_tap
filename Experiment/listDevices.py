import sounddevice as sd

def list_audio_devices():
    print("Available audio devices:\n")
    print(f"Default Devices: {sd.default.device}\n")
    print("Detailed Device Information:\n")
    print(f"  Input = {sd.query_devices(device=sd.default.device[0])}")
    print(f"  Output = {sd.query_devices(device=sd.default.device[1])}\n")
    
    devices = sd.query_devices()
    for idx, device in enumerate(devices):
        print(f"Device #{idx}: {device['name']}")
        print(f"  Host API         : {sd.query_hostapis(device['hostapi'])['name']}")
        print(f"  Max Input Channels : {device['max_input_channels']}")
        print(f"  Max Output Channels: {device['max_output_channels']}")
        print(f"  Default Sample Rate: {device['default_samplerate']}")
        print(f"  Default Low Input Latency : {device['default_low_input_latency']}")
        print(f"  Default High Input Latency: {device['default_high_input_latency']}")
        print(f"  Default Low Output Latency: {device['default_low_output_latency']}")
        print(f"  Default High Output Latency: {device['default_high_output_latency']}")
        print("-" * 60)

if __name__ == "__main__":
    list_audio_devices()