Smokeberry
==========

Code for controlling a smoker with a Rasberry Pi

Motivation
----------

The last time I smoked a brisket, I was bombarded by constant requests for status updates on the brisket.  (Of course, by "bombarded" I mean that a certain impatient Dutch astronomer would rather bug me from afar than come over and help me drink beer and see for his damn self)  To placate the masses (i.e. Remco) I have started grillduino.

System Description
-----------

Smokeberry is a suite of handware and programs which allow one to:
* Measure multiple grill temperatures via Temperature Probes
* Measure meat temperature (via a meat thermometer)
* Monitor/Control air flow via a PWM fan
* Adjust parameters of the control loop
* calibrate parameters of the control loop
* Manually enter meat temperature (via a dumb meat thermometer)
* Skeet if grill temperature is outside accepted norms (too hot/cold)
* Publish all temperatures to a SSH port
* Periodically plot interesting temperatures and upload to a website so that the masses can obsess over them.

This should be interesting...
