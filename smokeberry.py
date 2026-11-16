import os
import glob
import time
import requests
import threading
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

_cleanup_lock = threading.Lock()
_cleaned_up = False

def cleanup(pwm):
    # May be reached from more than one path on shutdown; only run once.
    global _cleaned_up
    with _cleanup_lock:
        if _cleaned_up:
            return
        _cleaned_up = True
    try:
        pwm.ChangeDutyCycle(0)
    except Exception:
        pass
    pwm.stop()
    GPIO.remove_event_detect(TACH_PIN)
    GPIO.cleanup()

def signal_handler(sig, frame):
    # Just request shutdown; main() does the cleanup in its finally block.
    stop_event.set()

VICTORIA_IMPORT_URL = "http://192.168.178.113:8428/api/v1/import/prometheus"
PUSH_TIMEOUT_SEC = 5.0

stop_event = threading.Event()      # whole program is shutting down
polling_stop = threading.Event()    # pause the sensor thread ("stop" command)
poll_wakeup = threading.Event()     # interrupt the sensor thread's wait early
poll_interval = 5.0                 # seconds; read by sensor_loop on every pass
latest_value_lock = threading.Lock()
latest_value = None

os.system('modprobe w1-gpio')
os.system('modprobe w1-therm')

base_dir = '/sys/bus/w1/devices/'
# Sorted so temp_1, temp_2, ... map to the same probes after every reboot.
device_folders = sorted(glob.glob(base_dir + '28*'))
device_files = [folder + '/w1_slave' for folder in device_folders]

TEMP_READ_RETRIES = 5

def read_temp_raw(therm):
    with open(therm, 'r') as f:
        return f.readlines()

def read_one_temp(thermometer):
    """Return the probe temperature in C, or None if it can't be read."""
    for _ in range(TEMP_READ_RETRIES):
        lines = read_temp_raw(thermometer)
        if len(lines) >= 2 and lines[0].strip()[-3:] == 'YES':
            equals_pos = lines[1].find('t=')
            if equals_pos != -1:
                return float(lines[1][equals_pos+2:]) / 1000.0
        time.sleep(0.2)
    return None

def read_temps():
    """One entry per probe, in device_files order; None for a failed probe."""
    temperatures = []
    for thermometer in device_files:
        try:
            temperatures.append(read_one_temp(thermometer))
        except Exception as e:
            print(f"[sensor] {thermometer}: {e}", file=sys.stderr)
            temperatures.append(None)
    return temperatures

def push_to_victoriametrics(temperature_samples, fan_samples):
    ts_ms = int(time.time() * 1000)
    lines = []
    for i, t_samp in enumerate(temperature_samples):
        if t_samp is not None:
            lines.append(f"temp_{i+1}_c {t_samp} {ts_ms}")

    if fan_samples is not None:
        lines.append(f"fan_duty_cycle {fan_samples[0]} {ts_ms}")
        lines.append(f"fan_rpm {fan_samples[1]} {ts_ms}")

    if not lines:
        return False

    payload = "\n".join(lines) + "\n"
    try:
        resp = requests.post(VICTORIA_IMPORT_URL, data=payload.encode("utf-8"),
                             headers={"Content-Type": "text/plain"},
                             timeout=PUSH_TIMEOUT_SEC)
        resp.raise_for_status()
        return True
    except Exception as e:
        print("Push error: ", e, file=sys.stderr)
        return False

def sensor_loop():
    global latest_value
    # Discard pulses counted while polling wasn't running.
    read_and_reset_pulses()
    last_rpm_time = time.monotonic()

    while not (stop_event.is_set() or polling_stop.is_set()):
        # Fan: divide by the real elapsed time, not the nominal poll interval,
        # since sensor reads and the HTTP push also take time.
        try:
            pulses = read_and_reset_pulses()
            now = time.monotonic()
            fan_rpm = compute_rpm(pulses, now - last_rpm_time)
            last_rpm_time = now
            fan_samples = [fan_dutyCycleSetPoint, fan_rpm]
        except Exception as e:
            fan_samples = None
            print(f"Fan read error: {e}", file=sys.stderr)

        temperature_samples = read_temps()
        if any(t is None for t in temperature_samples):
            print(time.strftime("%Y-%m-%d %H:%M:%S"), "Sensor read failed:",
                  temperature_samples, file=sys.stderr)

        with latest_value_lock:
            latest_value = [temperature_samples, fan_samples]

        push_to_victoriametrics(temperature_samples, fan_samples)

        # Wait for the interval, but wake immediately on setrate/stop/quit.
        poll_wakeup.wait(poll_interval)
        poll_wakeup.clear()

def input_loop():
    global poll_interval
    help_text = (
        "Commands:\n"
        "  read            - print latest sensor value\n"
        "  start           - resume sensor polling\n"
        "  stop            - pause sensor polling\n"
        "  setrate N       - set poll interval to N seconds (float)\n"
        "  setfan <0-100>  - set Fan duty cycle\n"
        "  quit / exit     - exit program\n"
        "  help            - show this message\n"
    )
    print(help_text)
    polling_thread = None

    # helper to (re)start polling thread
    def ensure_polling():
        nonlocal polling_thread
        if polling_thread is None or not polling_thread.is_alive():
            polling_stop.clear()
            poll_wakeup.clear()
            polling_thread = threading.Thread(target=sensor_loop, daemon=True)
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
            polling_stop.set()
            poll_wakeup.set()
            if polling_thread is not None:
                polling_thread.join()
            print("Sensor polling paused. Type 'start' to resume.")
        elif c == "start":
            ensure_polling()
            print("Polling running.")
        elif c == "setrate":
            if len(parts) >= 2:
                try:
                    new_rate = float(parts[1])
                    if new_rate <= 0:
                        raise ValueError
                    poll_interval = new_rate
                    poll_wakeup.set()   # cut the current wait short
                    print(f"Poll interval set to {poll_interval} s")
                except ValueError:
                    print("Invalid rate. Provide a positive number, e.g.,: setrate 0.2")
            else:
                print("Usage: setrate N")
        elif c == "setfan":
            if len(parts) == 2:
                try:
                    set_speed(pwm_instance, float(parts[1]))
                except ValueError:
                    print("Invalid value!")
            else:
                print("Usage: setfan <0-100>")
        else:
            print("Unknown command. Type 'help'.")


def main():
    init_gpio()
    global pwm_instance
    pwm_instance = init_pwm()

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    input_thread = threading.Thread(target=input_loop, daemon=True)
    input_thread.start()

    try:
        while input_thread.is_alive() and not stop_event.is_set():
            input_thread.join(timeout=0.5)
    finally:
        stop_event.set()
        poll_wakeup.set()
        cleanup(pwm_instance)

    print("Shutting down...")


if __name__ == "__main__":
    main()
