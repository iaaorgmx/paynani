# Marca de paynani

El isotipo es **la voluta**: la voluta de la palabra con que los códices dibujan
el habla saliendo de la boca, desenrollándose hacia afuera. Trazo de grosor
parejo con puntas redondas.

El manual completo —construcción, resguardo, usos incorrectos, color y
tipografía— vive en el issue [#27](https://github.com/iaaorgmx/paynani/issues/27).
Esta carpeta es la fuente de verdad de los archivos.

## Qué archivo usar

| Archivo | Cuándo |
|---|---|
| `voluta.svg` | Isotipo solo, sobre fondo claro. |
| `voluta-claro.svg` | Isotipo solo, sobre fondo oscuro. |
| `voluta-reducida.svg` | **De 24 px hacia abajo.** Es el mismo trazo sin el rizo interior. |
| `voluta-reducida-claro.svg` | La reducida, sobre fondo oscuro. |
| `favicon.svg` | Favicon y avatar. Es la reducida. |
| `paynani-horizontal.svg` | Logotipo completo. La opción por omisión. |
| `paynani-vertical.svg` | Cuando el ancho no alcanza. |
| `*-claro.svg` | Las mismas piezas para fondo oscuro. |
| `*-mono.svg` | Una sola tinta, con `currentColor`. Ver la advertencia de abajo. |

## Las cinco reglas

1. **El grosor no se toca.** Es `6` en un lienzo de `64`. No es un parámetro.
2. **Resguardo de `2x`**, donde `x` es el grosor del trazo. Nada entra ahí: ni
   texto, ni otro logotipo, ni el borde del soporte.
3. **Tamaño mínimo.** La principal no baja de 32 px; de ahí para abajo va la
   reducida, con 16 px como mínimo absoluto. En impreso, 12 mm de ancho de
   lienzo para la principal y 9 mm para la reducida.
4. **No se gira, no se rellena, no se deforma.** La boca apunta siempre arriba a
   la derecha, y la voluta es un trazo, no una silueta.
5. **Color sólo de la paleta**, y mínimo 4.5:1 contra el fondo.

## Paleta

| | HEX | RGB | CMYK de referencia |
|---|---|---|---|
| Grana cochinilla | `#8f2d2b` | 143 45 43 | 0 69 70 44 |
| Grana claro (fondo oscuro) | `#d8887f` | 216 136 127 | 0 37 41 15 |
| Tinta | `#1c1c1a` | 28 28 26 | 0 0 7 89 |
| Papel | `#f7f7f5` | 247 247 245 | 0 0 1 3 |
| Gris | `#66655f` | 102 101 95 | 0 1 7 60 |

Contrastes verificados: grana sobre papel **7.59:1** (AAA), grana claro sobre
`#16171a` **6.61:1** (AA), tinta sobre papel **15.91:1** (AAA).

El CMYK es una conversión directa desde RGB, para orientación. **No sirve para
imprenta**: hay que ajustarlo al papel y al perfil de la prensa.

## Advertencia sobre los `-mono`

Los archivos `*-mono.svg` usan `currentColor`, y eso **sólo hereda el color
cuando el SVG va en línea en el HTML**. Referenciados con `<img src="...">` se
pintan de negro, porque el documento del SVG no ve el `color` de la página que lo
incluye. Si vas a usar `<img>`, toma el archivo de color que corresponda
(`voluta.svg` o `voluta-claro.svg`), no el `-mono`.

## Las clases `.voluta` y `.logotipo`

Dentro de cada SVG, el trazo lleva `class="voluta"` y el logotipo en curvas lleva
`class="logotipo"`. No son decoración: son el punto de agarre para **insertar el
SVG en línea** y pintarlo con la hoja de estilos de la página, sin que exista una
segunda copia del dibujo en ningún lado.

Funciona porque una regla de CSS gana sobre un atributo de presentación, así que
los colores horneados en el archivo siguen siendo los correctos cuando el SVG se
abre solo o se referencia con `<img>`, y la página que lo inserta puede
repintarlo por tema:

```css
.marca .voluta   { stroke: var(--accent); }
.marca .logotipo { fill: var(--ink); }
```

Así lo usa la página de configuración del buzón —`webapp/lib/brand.php` la
inserta y `webapp/assets/app.css` la pinta—, que además no tenía alternativa: su
`Content-Security-Policy` es `default-src 'none'` sin `img-src`, de modo que una
imagen enlazada quedaría bloqueada.

**Si editas o regeneras los SVG, conserva las dos clases.**

## Tipografía

El logotipo va **en curvas** dentro de los SVG, así que ningún archivo depende de
tener una fuente instalada.

Las curvas provienen de **Spectral Medium**, de Production Type, distribuida bajo
[SIL Open Font License 1.1](https://openfontlicense.org) —
*Copyright 2017 The Spectral Project Authors*. El texto completo de la licencia
está en [`OFL-Spectral.txt`](OFL-Spectral.txt).

Para la interfaz y la documentación **no se usa Spectral ni ninguna otra fuente
remota**: va la tipografía del sistema. La razón está escrita en
`webapp/assets/app.css` y no es estética — paynani se instala en hosts que pueden
no tener salida a internet, y ahí una fuente remota no falla con estruendo, falla
en silencio.

## Voz gráfica

Las cinco reglas dicen qué no hacer. Esto dice cómo decidir cuando el caso no
está en la lista.

**El isotipo es un trazo, no una silueta.** De ahí sale casi todo lo demás. No se
rellena, no se encierra en un círculo ni en una pastilla: la voluta es habla
saliendo de una boca, y meterla en un contenedor la contradice — el encierro es
justamente lo que está dejando atrás. Si hace falta separarla del fondo, se
cambia el fondo, no se le pone marco.

**Un solo acento.** La grana cochinilla es el único color que la marca agrega. El
jade se retiró para no acabar con un sistema de dos colores compitiendo. Si algo
necesita un segundo color, es semántico —error, éxito, aviso— y no pertenece a la
marca: no lo tomes de la paleta ni lo llames color de paynani.

**El nombre es la otra mitad.** El isotipo va solo únicamente donde el nombre ya
está presente o no hace falta: favicon, avatar, marca de agua. En cualquier otro
sitio va el lockup. Un isotipo suelto en un lugar donde nadie ha leído «paynani»
no comunica la marca, la esconde.

**El espacio es material, no sobra.** El resguardo de `2x` es un mínimo, no un
objetivo. La marca aguanta mucho aire alrededor y se ve mal apretada; ante la
duda, más espacio.

**La cita no se disfraza.** El origen es la voluta de la palabra de los códices,
y esa referencia ya la carga el trazo. No se le suman grecas, escalonados,
pirámides ni bordes «prehispánicos»: eso convierte una cita en un disfraz, que
es exactamente el cliché del azteca decorativo que la marca existe para evitar.
La contención es lo que hace que la referencia se lea como intención y no como
adorno.

**La marca de agua es el único uso decorativo permitido**, al 6 % y **siempre
desbordando un borde**. Una voluta completa dentro del cuadro deja de leerse como
textura y se lee como un segundo logotipo. Ver `social-preview.html`.

**La boca apunta siempre arriba a la derecha.** No es una preferencia de
composición: es habla saliendo, y voltearla invierte la lectura.

**Sobre fondo oscuro se cambia de archivo, no de opacidad.** Para eso están los
`*-claro.svg`. Bajarle la opacidad a la versión clara ensucia el color y rompe el
contraste verificado en la paleta.

## Piezas exportadas

| Archivo | Dónde va |
|---|---|
| `social-preview.html` | Fuente del social preview del repositorio. |
| `paynani-social-preview-1280x640.png` | GitHub → Settings → General → Social preview. |

El PNG se versiona junto a su fuente por la misma razón que los SVG: **subir esa
imagen es interfaz web, no API**, así que el archivo tiene que existir para que
una persona pueda arrastrarlo. La primera versión vivió sólo fuera de `git` y se
perdió.

Para regenerarlo, desde `brand/`:

```bash
~/.claude/bin/web-shot.sh "file://$PWD/social-preview.html" \
    paynani-social-preview-1280x640.png --ancho 1280 --alto 640
```

La fuente **referencia** `paynani-horizontal.svg` con `<img>` en vez de copiar el
dibujo: funciona porque ese archivo lleva los colores horneados, y evita una
segunda copia que se quedaría atrás la próxima vez que la marca cambie. La voluta
de la marca de agua sí va en línea, porque necesita una opacidad que `<img>` no
puede imponerle desde fuera.

## Cómo se regeneran

Los SVG están generados, no dibujados a mano. El trazo de la voluta es un `path`
fijo y el logotipo se convierte a curvas con `fontTools` a partir del TTF de
Spectral. Si hay que rehacerlos, el procedimiento está en el issue #27.
