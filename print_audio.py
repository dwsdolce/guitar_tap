import pyaudio

def print_device_info(index):
    device = p.get_device_info_by_index(index)
    for key, value in device.items():
        print(f"{key} : {value}")

p = pyaudio.PyAudio()

default_input = p.get_default_input_device_info()
print(f'Default Input: {default_input["name"]}')

default_output = p.get_default_output_device_info()
print(f'Default Output: {default_output["name"]}')

for i in range(p.get_device_count()):
    print("=================")
    print_device_info(i)
