# -*- coding: utf-8 -*-
"""
Created on Wed Apr 15 12:10:59 2026

@author: Casey
"""

#!/usr/bin/env python3
import time
import RPi.GPIO as GPIO

# Configuration
SERVO_PIN = 19         # GPIO pin connected to servo signal (use a PWM-capable pin)
FREQ = 50              # 50 Hz typical for RC servos
MIN_PW_MS = 1.0        # pulse width for min position (ms) — adjust if needed
MAX_PW_MS = 2.0        # pulse width for max position (ms) — adjust if needed

# Helper: convert pulse width (ms) to duty cycle percent for given frequency
def pw_ms_to_duty(pw_ms, freq):
    period_ms = 1000.0 / freq
    return (pw_ms / period_ms) * 100.0

def clamp(v, a, b):
    return max(a, min(b, v))

def angle_to_pw_ms(angle_deg, min_pw=MIN_PW_MS, max_pw=MAX_PW_MS):
    # Map 0-180 degrees to min_pw..max_pw linearly
    angle = clamp(angle_deg, 0.0, 180.0)
    return min_pw + (angle / 180.0) * (max_pw - min_pw)

def angle_to_duty(angle_deg, freq=FREQ):
    pw = angle_to_pw_ms(angle_deg)
    return pw_ms_to_duty(pw, freq)

def setup():
    GPIO.setmode(GPIO.BCM)
    GPIO.setup(SERVO_PIN, GPIO.OUT)
    pwm = GPIO.PWM(SERVO_PIN, FREQ)
    pwm.start(angle_to_duty(90))  # start at neutral (90°)
    time.sleep(0.3)
    return pwm

def cleanup(pwm):
    pwm.stop()
    GPIO.cleanup()

# Example usage: sweep from 0 to 180 and back
if __name__ == "__main__":
    try:
        pwm = setup()
        step = 5
        delay = 0.02  # seconds between small steps for smooth motion

        # Sweep up
        for ang in range(0, 181, step):
            duty = angle_to_duty(ang)
            pwm.ChangeDutyCycle(duty)
            time.sleep(delay)

        time.sleep(0.5)

        # Sweep down
        for ang in range(180, -1, -step):
            duty = angle_to_duty(ang)
            pwm.ChangeDutyCycle(duty)
            time.sleep(delay)

        # Move to center
        pwm.ChangeDutyCycle(angle_to_duty(90))
        time.sleep(0.5)

    except KeyboardInterrupt:
        pass
    finally:
        cleanup(pwm)
