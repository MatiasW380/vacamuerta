# Vaca Muerta Monitor

Tablero público de la producción no convencional de Vaca Muerta, en inglés y castellano, con datos oficiales de la Secretaría de Energía (Capítulo IV, licencia CC BY 4.0).

## Cómo funciona

- `scripts/build_data.py` descarga el histórico de pozos no convencionales y los archivos anuales recientes, filtra la cuenca Neuquina y la formación Vaca Muerta y genera `data/vm.json`.
- `.github/workflows/update-data.yml` corre ese script todos los lunes, también a mano desde la pestaña Actions y cada vez que cambia el script. Si los datos cambian, hace commit y Vercel vuelve a publicar.
- `index.html` es la web estática: titular con el último mes, gráficos de petróleo y gas, ranking de operadoras, tablas y alta al newsletter.
- `api/subscribe.js` es la función de Vercel para el newsletter.

## Newsletter

El alta usa [Buttondown](https://buttondown.com). Creá una cuenta, copiá la API key y cargala en Vercel como variable de entorno `BUTTONDOWN_API_KEY` (Settings, Environment Variables). Sin esa variable el formulario avisa que las suscripciones abren pronto.

## Correr localmente

```bash
pip install -r scripts/requirements.txt
python scripts/build_data.py
python -m http.server 8000
```
