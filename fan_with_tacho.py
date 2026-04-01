#!/usr/bin/env python3
"""
San Ace 60T fan control + tachometer RPM reading for Raspberry Pi.

- PWM_PIN: BCM pin for PWM output (GPIO18 recommended).
- TACH_PIN: BCM pin for tachometer input (use a GPIO that supports interrupts).
- FREQ_HZ: PWM frequency in Hz.
- PULSES_PER_REV: tach pulses per fan revolution (common value: 2).
- RPM read method: counts pulses in a sampling window (non-blocking using interrupt).
"""

import time
import signal
import sys
import threading
import RPi.GPIO as GPIO

PWM_PIN = 18         # BCM - PWM output (GPIO18 recommended)
TACH_PIN = 24        # BCM - tachometer input (choose free GPIO)
FREQ_HZ = 2500       # PWM frequency
PULSES_PER_REV = 2   # change if fan uses different pulses per revolution
SAMPLE_INTERVAL = 1.0  # seconds for RPM sampling

# Shared counter for tach pulses
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
    # Tach callback on falling edge (fan FG typically pulses low)
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
    duty = max(0.0, min(100.0, float(duty)))
    pwm.ChangeDutyCycle(duty)

def ramp(pwm, start, end, duration=3.0, steps=50):
    start = max(0.0, min(100.0, float(start)))
    end = max(0.0, min(100.0, float(end)))
    if steps <= 0:
        set_speed(pwm, end)
        return
    sleep = max(0.0, duration / steps)
    for i in range(steps + 1):
        duty = start + (end - start) * (i / steps)
        set_speed(pwm, duty)
        time.sleep(sleep)

def cleanup(pwm):
    try:
        pwm.ChangeDutyCycle(0)
    except Exception:
        pass
    pwm.stop()
    GPIO.remove_event_detect(TACH_PIN)
    GPIO.cleanup()

def signal_handler(sig, frame):
    print("\nStopping and exiting.")
    cleanup(pwm_instance)
    sys.exit(0)

def rpm_monitor_loop(stop_event):
    # Periodically sample pulses and compute RPM
    while not stop_event.is_set():
        time.sleep(SAMPLE_INTERVAL)
        pulses = read_and_reset_pulses()
        rpm = compute_rpm(pulses, SAMPLE_INTERVAL)
        print(f"RPM: {rpm:.1f}  (pulses={pulses})")

if __name__ == "__main__":
    init_gpio()
    pwm_instance = init_pwm()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    stop_event = threading.Event()
    monitor_thread = threading.Thread(target=rpm_monitor_loop, args=(stop_event,), daemon=True)
    monitor_thread.start()

    try:
        print("Fan control with RPM monitoring.")
        print("Commands:")
        print("  q: quit")
        print("  s <0-100>: set duty cycle")
        print("  r <0-100> <0-100> <seconds>: ramp from A to B in T seconds")
        print("Example: s 50   r 0 100 5")
        while True:
            cmd = input("cmd> ").strip().split()
            if not cmd:
                continue
            c = cmd[0].lower()
            if c == 'q':
                break
            if c == 's' and len(cmd) >= 2:
                try:
                    set_speed(pwm_instance, float(cmd[1]))
                except ValueError:
                    print("Invalid value")
                continue
            if c == 'r' and len(cmd) >= 4:
                try:
                    a = float(cmd[1]); b = float(cmd[2]); t = float(cmd[3])
                    ramp(pwm_instance, a, b, duration=t)
                except ValueError:
                    print("Invalid values")
                continue
            print("Unknown command")
    finally:
        stop_event.set()
        monitor_thread.join(timeout=1.0)
        cleanup(pwm_instance)
        print("Exited.")
