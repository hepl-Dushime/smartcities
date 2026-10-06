from machine import Pin, PWM, ADC
from time import sleep

buzzer = PWM(Pin(16))
pot = ADC(Pin(27))

def DO(time):
    buzzer.freq(1046)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def RE(time):
    buzzer.freq(1175)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def MI(time):
    buzzer.freq(1318)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def FA(time):
    buzzer.freq(1397)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def SO(time):
    buzzer.freq(1568)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def LA(time):
    buzzer.freq(1760)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def SI(time):
    buzzer.freq(1967)
    buzzer.duty_u16(pot.read_u16())
    sleep(time)

def N(time):
    buzzer.duty_u16(0)
    sleep(time)

while True:

    DO(0.5)
    RE(0.5)
    MI(0.5)
    DO(0.5)
    N(0.02)

    DO(0.5)
    RE(0.5)
    MI(0.5)
    DO(0.5)

    MI(0.5)
    FA(0.5)
    SO(1)

    MI(0.5)
    FA(0.5)
    SO(1)
    N(0.02)

    SO(0.25)
    LA(0.25)
    SO(0.25)
    FA(0.25)
    MI(0.5)
    DO(0.5)

    SO(0.25)
    LA(0.25)
    SO(0.25)
    FA(0.25)
    MI(0.5)
    DO(0.5)

    RE(0.5)
    SO(0.5)
    DO(1)
    N(0.02)

    RE(0.5)
    SO(0.5)
    DO(1)

    N(1)