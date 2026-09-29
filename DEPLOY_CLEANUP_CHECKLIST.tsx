SPORTS PREDICTOR — LIMPIEZA DEL MODELO LEGACY
================================================

Objetivo
--------
Dejar 2.0.0-matchup como único modelo activo de nuevas predicciones.
No borrar registros históricos de la base de datos.

Archivos a reemplazar
---------------------
1. main.py
   - Elimina POST /api/v1/predictions/experimental.
   - Mantiene CURRENT_MODEL_VERSION = 2.0.0-matchup.
   - Mantiene el endpoint /api/v1/analyze y el flujo actual.

2. test_matchup.py
   - Actualiza las pruebas al contrato actual de matchup_engine.py.

3. verify_single_model.py
   - Verifica que main.py ya no exponga la ruta experimental.
   - Verifica que prediction.py use 2.0.0-matchup.

Archivos que NO deben reemplazarse en esta etapa
------------------------------------------------
- prediction.py actual
- analyzer.py actual
- matchup_engine.py actual
- repository.py actual

Motivo: la prueba Cubs vs Padres ya demuestra que el flujo 2.0.0-matchup
funciona con pitchers, splits, forma, bullpen, H2H y calidad 100%.

Pruebas locales / CI
--------------------
python -m py_compile main.py analyzer.py prediction.py matchup_engine.py repository.py
python verify_single_model.py
pytest -q test_matchup.py
pytest -q test_prediction.py test_prediction_engine.py test_split_engine.py test_pitcher_engine.py test_form.py

Después del deploy en Render
----------------------------
1. GET /health
   Debe responder status=ok y model_version=2.0.0-matchup.

2. GET /api/v1/mlb/games?day=YYYY-MM-DD
   Verificar que devuelve partidos Scheduled.

3. POST /api/v1/analyze
   Probar un partido futuro Scheduled.
   Confirmar model_version=2.0.0-matchup.

4. Confirmar que /api/v1/predictions/experimental ya no existe.
   Debe devolver 404.

5. Confirmar que una nueva predicción guardada usa 2.0.0-matchup.

6. No ejecutar DELETE/UPDATE masivo sobre prediction_snapshots.
   Los registros antiguos se conservan como historial.

Criterio de salida
------------------
La limpieza está terminada cuando:
- no existe el endpoint experimental;
- 2.0.0-matchup es la versión activa;
- una nueva predicción no puede crear MLB-Baseline-0.1;
- el análisis pregame sigue funcionando;
- los históricos permanecen intactos;
- settlement sigue pudiendo producir CORRECT/INCORRECT.
