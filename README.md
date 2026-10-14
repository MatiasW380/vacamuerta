# Argentina Invest Monitor

Portal de datos públicos de Argentina ordenados para inversores, en inglés y castellano. Cada sector tiene su tablero, alimentado automáticamente por fuentes oficiales y gratuitas.

| Ruta | Contenido | Estado |
| --- | --- | --- |
| `/` | Portada: datos del día, sectores, normativa y noticias | En vivo |
| `/vaca-muerta/` | Energía: producción, mapa de bloques, fractura, operadoras, precios, normativa | En vivo |
| Minería, agro, finanzas, industria | Próximos tableros | En desarrollo |

Estilos compartidos en `assets/site.css`. Todos los datos viven en `data/` y se sirven con rutas absolutas (`/data/...`).

## Cómo funciona

- `scripts/build_data.py` descarga el histórico de pozos no convencionales y los archivos anuales recientes, filtra la cuenca Neuquina y la formación Vaca Muerta y genera `data/vm.json`.
- `.github/workflows/update-data.yml` corre ese script todos los lunes, también a mano desde la pestaña Actions y cada vez que cambia el script. Si los datos cambian, hace commit y Vercel vuelve a publicar.
- `vaca-muerta/index.html` es el tablero de energía: titular con el último mes, gráficos de petróleo y gas, ranking de operadoras, tablas y alta al newsletter.
- `api/subscribe.js` es la función de Vercel para el newsletter.

## Newsletter

**Alta.** `api/subscribe.js` suma cada suscriptor a [Buttondown](https://buttondown.com) con la etiqueta de su idioma (`lang-es`, `lang-en`, `lang-pt`, `lang-el`). Necesita la API key en Vercel como variable de entorno `BUTTONDOWN_API_KEY`.

**Edición semanal.** `scripts/build_newsletter.py` arma cada lunes una edición en los cuatro idiomas con los datos de `data/`: Vaca Muerta, mercados y macro, aprobaciones RIGI del último mes, normas del Boletín Oficial de la semana, otros sectores, noticias y el bloque del estudio. La guarda en `newsletter/<año>-W<semana>/<idioma>.md` y la sube a Buttondown como **borrador**, una por idioma, dirigida solo a los suscriptores de esa etiqueta. No duplica una edición que ya existe.

- Lo corre `.github/workflows/newsletter.yml` los lunes a las 10:41 (hora argentina), después de la actualización de datos.
- Necesita la misma API key como secreto del repositorio: GitHub → Settings → Secrets and variables → Actions → `BUTTONDOWN_API_KEY`. Sin ella solo guarda los archivos.
- Revisás cada borrador en Buttondown y lo enviás. Desde la pestaña Actions se puede correr a mano y marcar "Enviar directamente".
- Si un idioma todavía no tiene suscriptores, ese borrador no se crea.

## Correr localmente

```bash
pip install -r scripts/requirements.txt
python scripts/build_data.py
python -m http.server 8000
```
