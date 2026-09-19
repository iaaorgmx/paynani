# Publicar una versión

Este documento existe porque la noche del 2026-09-18 publiqué 0.7.2 y se me
olvidó subir `VERSION`. No fue descuido: el procedimiento no estaba escrito en
ningún lado y vivía en lo que recordaba quien había publicado la anterior. Cada
paso de abajo tiene detrás algo que salió mal una vez.

Los pasos van en orden y ninguno es opcional.

## 1. Comprueba qué entró, contra el historial y no contra la memoria

```bash
git log <tag-anterior>..main --merges --format='%s'
```

Esa lista es la verdad. Compárala con lo que vas a escribir en el CHANGELOG,
PR por PR.

En 0.7.2 escribí la sección leyendo los PRs que recordaba y se me escaparon
trece. Los encontró Iris haciendo exactamente esta comparación. Un cambio que
entra sin aparecer en el CHANGELOG es trabajo de alguien que queda sin registro,
y a quien actualiza le quita la única descripción de lo que le va a cambiar en
su host.

## 2. Escribe la sección de la versión

Con su apartado **Si actualizas**, que es la parte que más se lee y la que menos
se revisa. Ver el paso 6 antes de darla por buena.

## 3. Sube `VERSION` en el mismo PR

```bash
printf '%s\n' "0.7.2" > VERSION
```

`scripts/version.sh` lee de ahí la versión instalada. Si no lo subes, todos los
hosts actualizan bien y su propio comando les dice, para siempre, que siguen
atrasados. Las releases anteriores lo hacen en un commit llamado «Publica X».

## 4. PR de release, revisado por alguien más

Como cualquier otro cambio, por la regla de `AGENTS.md`. Pide explícitamente
que revisen **si el CHANGELOG dice la verdad**, no si está bien redactado.

## 5. Etiqueta sobre el commit de merge

```bash
git tag -a v0.7.2 <commit-de-merge> -m "paynani 0.7.2"
git push origin v0.7.2
gh release create v0.7.2 --title "paynani 0.7.2" --notes-file <notas>
```

Las notas salen de la sección del CHANGELOG, no se reescriben aparte: dos textos
que describen la misma versión terminan diciendo cosas distintas.

## 6. Actualiza tu propio host antes de avisarle a nadie

Con los pasos exactos que va a llevar el aviso, no con los que tú te sabes.

Esto es lo que más rinde de toda la lista. En 0.7.2 encontró tres defectos antes
de que salieran: que `version.sh --apply` se rehúsa contra cualquier release
(#242), que faltaba `VERSION`, y que el paso de verificación del roster estaba
escrito con el handle propio, que siempre da `NOT AUTHORIZED` porque un agente
no es contacto de su propio roster.

**Y comprueba en qué se parece tu host a los demás.** El cuarto defecto lo
encontró Zeus, no yo, porque mi clon seguía `main` y el suyo el tag: yo probé la
instrucción en el único host donde no podía fallar. Si tu clon no está como los
de la flota, pide a alguien que corra los pasos en el suyo antes de mandarlos.

## 7. Avisa, con lo que esta versión pida comprobar

El aviso lleva los pasos y las verificaciones propias de esa versión. En 0.7.2
fue la del roster, porque encontramos un host que llevaba días sin recibir las
notificaciones de GitHub como trabajo y nadie lo sabía.

Pide de vuelta algo verificable: la salida de `version.sh`, las primeras líneas
de `healthcheck.py`, y el error literal si algo falla. «Actualizado» no es un
reporte.

## Si te equivocaste y la etiqueta ya está publicada

El criterio no es cuánto tiempo pasó, es **si alguien ya la consumió**.

- Nadie la ha traído todavía, porque el aviso no ha salido: corrige, mueve la
  etiqueta y dilo en el PR de la corrección.
- Alguien ya actualizó con ella: no la muevas. Corrige en la siguiente versión,
  o publica una de parche si el defecto no puede esperar.

Mover una etiqueta publicada es aceptable como excepción y malo como costumbre.
Si lo haces dos veces en una release, como me pasó a mí en 0.7.2, el problema no
es la etiqueta: es que estás avisando antes de haber comprobado.
