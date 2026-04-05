import os
import glob
import time

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

base_dir = '/sys/bus/w1/devices/'
device_folders =  glob.glob(base_dir + '28*')

i = 1
device_files = []
for folder in device_folders:
    device_files.append(folder + '/w1_slave')
    i += 1

def read_temp_raw(therm):
    f = open(therm, 'r')
    lines = f.readlines()
    f.close()
    return lines
    
def read_temps():
    i = 1
    temperatures = ''
    for thermometer in device_files:
        lines = read_temp_raw(thermometer)
        while lines[0].strip()[-3:] != 'YES':
            time.sleep(0.2)
            lines = read_temp_raw()
        equals_pos = lines[1].find('t=')
        if equals_pos != -1:
            temp_string = lines[1][equals_pos+2:]
            temp_c = float(temp_string) / 1000.0
            temperatures += 'Thermometer %d : %.2f\n' % (i, temp_c)
        i += 1
    return temperatures
	    
while True:
    print(read_temps())
    time.sleep(1)
