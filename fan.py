#!/usr/bin/env python3
"""
Simple San Ace 60T fan control for Raspberry Pi using RPi.GPIO PWM.

- Uses GPIO18 (pin 12) by default (hardware PWM pin on many Pis).
- Controls fan speed by duty cycle (0-100).
- Safe-guards: never sets PWM > 100 or < 0.
- Requires separate 12V power for the fan and common ground.
"""

import time
import signal
import sys
import RPi.GPIO as GPIO

PWM_PIN = 18        # BCM pin number (GPIO18 recommended)
FREQ_HZ = 250     # 25 kHz typical PWM frequency for PC fans (can be 25kHz or 25000)
DEFAULT_DUTY = 0    # start stopped

def init():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(PWM_PIN, GPIO.OUT)
    # Use hardware PWM where possible
    pwm = GPIO.PWM(PWM_PIN, FREQ_HZ)
    pwm.start(DEFAULT_DUTY)
    return pwm

def set_speed(pwm, duty):
    # clamp duty cycle
    if duty is None:
        return
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
    GPIO.cleanup()

def signal_handler(sig, frame):
    print("\nStopping fan and exiting.")
    cleanup(pwm_instance)
    sys.exit(0)

if __name__ == "__main__":
    pwm_instance = init()
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    try:
        print("Fan control running. Commands:")
        print("  q/Q: quit")
        print("  s <0-100>: set duty cycle")
        print("  r <0-100> <0-100> <seconds>: ramp from A to B in T seconds")
        print("Examples: 's 50'  'r 0 100 5'")

        while True:
            cmd = input("cmd> ").strip().split()
            if not cmd:
                continue
            if cmd[0].lower() == 'q':
                break
            if cmd[0].lower() == 's' and len(cmd) >= 2:
                try:
                    set_speed(pwm_instance, float(cmd[1]))
                except ValueError:
                    print("Invalid value")
                continue
            if cmd[0].lower() == 'r' and len(cmd) >= 4:
                try:
                    a = float(cmd[1])
                    b = float(cmd[2])
                    t = float(cmd[3])
                    ramp(pwm_instance, a, b, duration=t)
                except ValueError:
                    print("Invalid values")
                continue
            print("Unknown command")
    finally:
        cleanup(pwm_instance)
        print("Exited.")
