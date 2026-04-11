import os
import glob
import time
import requests
from prometheus_client import CollectorRegistry, Gauge, generate_latest
import threading
import time
import queue
import sys
import signal
import RPi.GPIO as GPIO

PWM_PIN = 18
TACH_PIN = 24
FREQ_HZ = 2500
PULSES_PER_REV = 2

fan_dutyCycleSetPoint = 0.0
# shared counter for tach pulses
_pulse_count = 0
_pulse_lock = threading.Lock()

def tach_callback(channel):
    global _pulse_count
    with _pulse_lock:
        _pulse_count += 1

def init_gpio():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PWM_PIN, GPIO.OUT)
    GPIO.setup(TACH_PIN, GPIO.IN, pull_up_down=GPIO.PUD_UP)
    GPIO.add_event_detect(TACH_PIN, GPIO.FALLING, callback=tach_callback, bouncetime=1)

def init_pwm():
    pwm = GPIO.PWM(PWM_PIN, FREQ_HZ)
    pwm.start(0.0)
    return pwm

def read_and_reset_pulses():
    global _pulse_count
    with _pulse_lock:
        count = _pulse_count
        _pulse_count = 0
    return count

def compute_rpm(pulse_count, interval_sec):
    if interval_sec <= 0:
        return 0.0
    revs = pulse_count / float(PULSES_PER_REV)
    rpm = (revs / interval_sec) * 60.0
    return rpm

def set_speed(pwm, duty):
    global fan_dutyCycleSetPoint
    duty = max(0.0, min(100.0, float(duty)))
    fan_dutyCycleSetPoint = duty
    pwm.ChangeDutyCycle(duty)

def cleanup(pwm):
    try:
        pwm.ChangeDutyCycle(0)
    except Exception:
        pass
    pwm.stop()
    GPIO.remove_event_detect(TACH_PIN)
    GPIO.cleanup()

def signal_handler(sig, frame):
    stop_event.set()
    cleanup(pwm_instance)
    sys.exit(0)

VICTORIA_PUSH_URL = "http://192.168.178.113:8428/api/v1/prom/remote/write"
NAS_PATH = "/var/lib/victoria-metrics/"
#NAS_PATH = "/mnt/vmdata/Data/Smokeberry/"

HTTP_HEADERS = {"Content-Type": "application/x-protobuf"}

stop_event = threading.Event()
command_q = queue.Queue()
latest_value_lock = threading.Lock()
latest_value = None

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
	    
def push_to_victoriametrics(temperature_samples, fan_samples):
    ts_ms = int(time.time() * 1000)
    #print(ts_ms)
    lines = []
    for i, t_samp in enumerate(temperature_samples):
        lines.append(f"temp_{i+1}_c {t_samp} {ts_ms}")
    
    lines.append(f"fan_duty_cycle {fan_samples[0]} {ts_ms}")
    lines.append(f"fan_rpm {fan_samples[1]} {ts_ms}")
    
    payload = "\n".join(lines) + "\n"
    #print(payload)
    url = VICTORIA_PUSH_URL.replace("/prom/remote/write", "/import/prometheus")
    try:
        resp = requests.post(url, data=payload.encode("utf-8"), headers={"Content-Type": "text/plain"})
        resp.raise_for_status()
        return True
    except Exception as e:
        print("Push error: ", e)
        return False

def sensor_loop(poll_interval):
    global latest_value
    #print("Ä: ", poll_interval)
    while not stop_event.is_set():
        try:
            temperature_samples = read_temps()
        except Exception as e:
            # handle sensor read error
            temperature_samples = None
            print(f"[sensor] read error: {e}", file=sys.stderr)
        #with latest_value_lock:
        #    latest_value = temperature_samples

        try:
            pulses = read_and_reset_pulses()
            fan_rpm = compute_rpm(pulses, poll_interval)
            fan_samples = [fan_dutyCycleSetPoint, fan_rpm]
        except Exception as e:
            fan_samples = None
            print(f"Fan read error: {e}", file=sys.stderr)
        with latest_value_lock:
            latest_value = [temperature_samples, fan_samples]

        if (len(temperature_samples) == 2) and (len(fan_samples) == 2):
            ok = push_to_victoriametrics(temperature_samples, fan_samples)
        else:
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "Sensor read failed")
        print("Poll Interval :", poll_interval)
        time.sleep(poll_interval)

def input_loop():
    global pwm_instance
    help_text = (
        "Commands:\n"
        "  read            - print latest sensor value\n"
        "  start           - ensure sensor polling is running\n"
        "  stop            - pause sensor polling\n"
        "  setrate N       - set poll interval to N seconds (float)\n"
        "  setfan <0-100>  - set Fan duty cycle\n"
        "  quit / exit     - exit program\n"
        "  help            - show this message\n"
    )
    print(help_text)
    poll_interval = 5.0
    polling_thread = None

    # helper to (re)start polling thread
    def ensure_polling():
        nonlocal polling_thread
        #print('Restarting Polling Thread: ', poll_interval)
        if polling_thread is None or not polling_thread.is_alive():
            polling_thread = threading.Thread(target=sensor_loop, args=(poll_interval,), daemon=True)
            polling_thread.start()

    ensure_polling()

    while not stop_event.is_set():
        try:
            cmd = input("> ").strip()
        except EOFError:
            # e.g., user pressed Ctrl+D
            stop_event.set()
            break
        if not cmd:
            continue
        parts = cmd.split()
        c = parts[0].lower()
        if c in ("quit", "exit"):
            stop_event.set()
            break
        elif c == "help":
            print(help_text)
        elif c == "read":
            with latest_value_lock:
                print(time.strftime("%Y-%m-%d %H:%M:%S"), "Sample :", latest_value)
        elif c == "stop":
            stop_event.set()
            print("Stopping sensor polling...")
            # Create a new event so program can be restarted? Keep simple: exit loop.
        elif c == "start":
            if stop_event.is_set():
                print("Cannot restart after stop in this run. Please restart program.")
            else:
                ensure_polling()
                print("Polling running.")
        elif c == "setrate":
            if len(parts) >= 2:
                try:
                    new_rate = float(parts[1])
                    if new_rate <= 0:
                        raise ValueError
                    poll_interval = new_rate
                    # restart polling thread with new interval by stopping and starting a new thread
                    stop_event.set()
                    time.sleep(0.1)
                    # reset and start fresh
                    stop_event.clear()
                    ensure_polling()
                    print('B: Polling Interval :', poll_interval)
                    print(f"Poll interval set to {poll_interval} s")
                except ValueError:
                    print("Invalid rate. Provide a positive number, e.g.,: setrate 0.2")
                print('C: Polling Interval :', poll_interval)
            else:
                print("Usage: setrate N")
        elif c == "setfan":
            if len(parts) == 2:
                try:
                    set_speed(pwm_instance, float(parts[1]))
                except ValueError:
                    print("Invalid value!")
                continue
        else:
            print("Unknown command. Type 'help'.")


def main():
    init_gpio()
    global pwm_instance
    pwm_instance = init_pwm()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    input_thread = threading.Thread(target=input_loop, daemon=True)
    #monitor_thread = threading.Thread(target=rpm_monitor_loop, args=(stop_event,), daemon=True)

    input_thread.start()
    #monitor_thread.start()

    try:
        #while (input_thread.is_alive()) and (monitor_thread.is_alive()):
        while input_thread.is_alive():
            input_thread.join(timeout=0.5)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        stop_event.set()
        #monitor_thread.join(timeout=1.0)
        cleanup(pwm_instance)

    print("Shutting down...")


if __name__ == "__main__":
    main()
