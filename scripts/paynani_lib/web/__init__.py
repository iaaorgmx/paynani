"""
PaynaniWeb: la aplicación web para administrar paynani (PRD #434, paraguas #435).

Un proceso aparte (scripts/paynani_web.py) que escucha en 127.0.0.1:8771. Desde
fuera se llega por la pasarela SMS, que le reenvía todo lo que no es de /sms/
(FR-1). Sólo biblioteca estándar.
"""
