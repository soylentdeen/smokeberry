import os
import glob
import time
import requests
from prometheus_client import CollectorRegistry, Gauge, generate_latest

VICTORIA_PUSH_URL = "http://192.168.178.113:8428/api/v1/prom/remote/write"
NAS_PATH = "/var/lib/victoria-metrics/"
#NAS_PATH = "/mnt/vmdata/Data/Smokeberry/"

HTTP_HEADERS = {"Content-Type": "application/x-protobuf"}

if not os.path.isdir(NAS_PATH):
    os.makedirs(NAS_PATH, exist_ok=True)

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

base_dir = '/sys/bus/w1/devices/'
device_folders =  glob.glob(base_dir + '28*')

i = 1
device_files = []
for folder in device_folders:
    device_files.append(folder + '/w1_slave')
    i+=1

def read_temp_raw(therm):
    f = open(therm, 'r')
    lines = f.readlines()
    f.close()
    return lines
    
def read_temps():
    temperatures = []
    for thermometer in device_files:
        lines = read_temp_raw(thermometer)
        while lines[0].strip()[-3:] != 'YES':
            time.sleep(0.2)
            lines = read_temp_raw(thermometer)
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos+2:]
            temp_c = float(temp_string) / 1000.0
            temperatures.append(temp_c)
    return temperatures
	    
def push_to_victoriametrics(sample):
    ts_ms = int(time.time() * 1000)
    print(ts_ms)
    lines = []
    for i, samp in enumerate(sample):
        lines.append(f"temp_{i+1}_c {samp} {ts_ms}")
    
    payload = "\n".join(lines) + "\n"
    print(payload)
    url = VICTORIA_PUSH_URL.replace("/prom/remote/write", "/import/prometheus")
    try:
        resp = requests.post(url, data=payload.encode("utf-8"), headers={"Content-Type": "text/plain"})
        resp.raise_for_status()
        return True
    except Exception as e:
        print("Push error: ", e)
        return False

def main():
    while True:
        sample = read_temps()
        print(sample)
        if len(sample) == 2:
            ok = push_to_victoriametrics(sample)
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "Sample :", sample, "pushed: ", ok)
        else:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "Sensor read failed")
        time.sleep(1)

if __name__ == "__main__":
    main()
