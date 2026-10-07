# lightbox_calpaca-drivers
Lightbox with Alpaca drivers to be used for lights in astrofotography
**Why this project**
When you doing astrophotography, you need a lightbox that is dimmable to allow taking "flats", so you can capture the optical limitations so corrections are possible.  The lightbox needs to be dimmable because to much light will overexpose all optical issues.
Some years ago, I bought a Lacerta dimmable lightbox but not the controller as this was another USB connected device.

However, over the last years, we have the uprise of ESP32 devices supporting micropython and the launch of the [Alpaca protocol of ASCOM].(https://www.ascom-alpaca.org/)

Combining AI code generation, ESP32 with micropython and the Alpaca ASCOM protocol is now allowing an easy DIY wifi lightbox.

![Lightbox photo](https://github.com/HenkUyttenhove/lightbox_calpaca-drivers/blob/main/lightbox.jpg)

**Defined requirements**
- The controller needs to be powered using a 12V power outlet and deliver a 12V power outlet for the lightbox
- The controller will, as a default, automatically connect to my home Wifi network and when not available, activate his own AP
- The controller can be controlled via the Alpaca protocol on NiNa or Kstars or any other software supporting Alpaca
- The controller has also a webportal where you can manually change the light or enter an alternative Wifi network


