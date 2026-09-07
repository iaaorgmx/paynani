#!/usr/bin/env python3
"""Prueba rota A PROPOSITO. No fusionar.

Existe para demostrar la cuarta casilla del criterio de cierre del #67: que un
PR con una prueba en rojo queda bloqueado por la proteccion de rama, y no solo
marcado en rojo mientras el boton de fusionar sigue disponible.

El PR que la trae se cierra sin fusionar. Si este archivo aparece alguna vez en
`main`, algo salio muy mal.
"""
import sys

print("fallo deliberado: demostracion de la compuerta del #67")
sys.exit(1)
