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

El alta usa [Buttondown](https://buttondown.com). Creá una cuenta, copiá la API key y cargala en Vercel como variable de entorno `BUTTONDOWN_API_KEY` (Settings, Environment Variables). Sin esa variable el formulario avisa que las suscripciones abren pronto.

## Correr localmente

```bash
pip install -r scripts/requirements.txt
python scripts/build_data.py
python -m http.server 8000
```
