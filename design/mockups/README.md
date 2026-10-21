# Mockups

| ID | Pantalla | Origen |
|---|---|---|
| `PDSL-100` | Entrar o registrarse | Composición de NDSL-100, con la marca de paynani |
| `PDSL-201` | Perfil, con el menú de la aplicación web de administración | Composición de NDSL-201, con la marca de paynani y el menú definido por Julian |

Cada PNG (1920×953) se genera de su HTML en `src/`, que toma el logotipo de
`brand/` con `<img>` en lugar de copiarlo. Para regenerar, desde la raíz del repo:

```bash
python render.py design/mockups/src/PDSL-201.html design/mockups/PDSL-201.png
```

donde `render.py` abre el HTML en Chromium sin cabeza (Playwright) con una ventana
de 1920×953 y guarda la captura.
