
from machine import Pin, PWM, ADC, I2C
from lcd1602 import LCD1602
from dht11 import *
from utime import sleep, ticks_ms, ticks_diff

pot = ADC(Pin(26))
dht = DHT(18)
led = Pin(15, Pin.OUT)
buzzer = PWM(Pin(16))

i2c = I2C(1, scl=Pin(7), sda=Pin(6), freq=400000)
d = LCD1602(i2c, 2, 16)
d.display()

led.value(0)
buzzer.duty_u16(0)

dernier_clignotement = ticks_ms()
dernier_capteur = ticks_ms() - 1000

etat_led = 0
temp = None

while True:

    maintenant = ticks_ms()

    valeur = pot.read_u16()
    consigne = 15 + (valeur / 65535) * 20

    if ticks_diff(maintenant, dernier_capteur) >= 1000:

        dernier_capteur = maintenant

        try:
            temp, humid = dht.readTempHumid()

            d.clear()

            d.setCursor(0, 0)
            d.print("Set: {:.1f} C".format(consigne))

            d.setCursor(0, 1)
            d.print("Ambient: {} C".format(temp))

            if temp > consigne + 3:
                d.setCursor(11, 0)
                d.print("ALARM")

        except Exception as e:
            print("Erreur capteur:", e)

    if temp is not None:

        if temp > consigne + 3:

            buzzer.freq(1000)
            buzzer.duty_u16(1000)
            intervalle = 250

        elif temp > consigne:

            buzzer.duty_u16(0)
            intervalle = 1000

        else:

            buzzer.duty_u16(0)
            led.value(0)
            etat_led = 0
            intervalle = 0

    else:
        buzzer.duty_u16(0)
        led.value(0)
        etat_led = 0
        intervalle = 0

    if intervalle > 0:

        if ticks_diff(maintenant, dernier_clignotement) >= intervalle:

            dernier_clignotement = maintenant

            etat_led = 1 - etat_led
            led.value(etat_led)

    sleep(0.02)

