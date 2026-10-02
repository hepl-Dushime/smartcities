import machine
import utime

BOUTTON = machine.Pin(16, machine.Pin.IN, machine.Pin.PULL_UP)
LED = machine.Pin(18, machine.Pin.OUT)

compteur = 0
ancien_bouton = 1
dernier_temps = utime.ticks_ms()

while True:

    val = BOUTTON.value()

    # Nouvel appui sur le bouton
    if val == 0 and ancien_bouton == 1:
        compteur += 1

        if compteur > 3:
            compteur = 1

        print("compteur =", compteur)

        # anti-rebond
        utime.sleep_ms(50)

    ancien_bouton = val

    # 1er appui : 0,5 Hz
    if compteur == 1:
        if utime.ticks_diff(utime.ticks_ms(), dernier_temps) >= 1000:
            LED.value(not LED.value())
            dernier_temps = utime.ticks_ms()

    # 2e appui : 2 Hz
    elif compteur == 2:
        if utime.ticks_diff(utime.ticks_ms(), dernier_temps) >= 250:
            LED.value(not LED.value())
            dernier_temps = utime.ticks_ms()

    # 3e appui : LED éteinte
    elif compteur == 3:
        LED.value(0)