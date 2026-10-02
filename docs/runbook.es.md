# Runbook de recuperación ante desastres — bases de datos de la clínica

Este runbook se ejercita en el simulacro de CI: los comandos de abajo son los que ejecuta `scripts/run-drill.sh`,
así que cada push a `main` y cada ejecución semanal prueban que siguen funcionando. Cubre la recuperación desde
copias de seguridad; la alta disponibilidad y las copias de máquinas virtuales están fuera del alcance.

## 1. Propósito y alcance

| Sistema | Motor | Qué hace | Objetivo RPO | Objetivo RTO |
|---|---|---|---|---|
| `appointments` | SQL Server 2025 | citas — el sistema central | ≤ 15 min | ≤ 30 min |
| `billing` | PostgreSQL 18 | facturas | ≤ 5 min | ≤ 60 min |

El **RPO** (objetivo de punto de recuperación) es cuántos datos acepta perder el negocio, medido en tiempo. El
**RTO** (objetivo de tiempo de recuperación) es cuánto puede tardar, desde que se declara la recuperación hasta que
el sistema está verificado y utilizable. Los objetivos están en `policy/dr-policy.yaml`.

Las copias tienen dos niveles:

- **Local**: el recurso compartido de copias. SQL Server escribe copias completas (diarias), diferenciales (cada
  6 h) y de log (cada 15 min); PostgreSQL escribe una copia base (semanal) y archiva su write-ahead log de forma
  continua. Rápido para restaurar, pero alcanzable por un atacante que llegue a los servidores de bases de datos.
- **Externo**: un bucket de almacenamiento de objetos con **Object Lock en modo compliance**. Cada copia terminada se
  copia allí con una fecha de retención y queda registrada en un manifiesto con su versión de objeto y su SHA-256.
  Hasta la fecha de retención nadie — ni la clave de copias ni un administrador — puede borrar una versión
  bloqueada ni acortar su retención.

## 2. Roles

| Rol | Responsabilidades |
|---|---|
| Comandante del incidente | Declara el incidente, lleva la línea de tiempo y las decisiones de abajo, convoca a los demás |
| DBA de guardia | Ejecuta las restauraciones y la verificación, informa el avance frente al RTO |
| Responsable de seguridad | Decide qué es confiable, fija T0 (ver D3), preserva la evidencia, rota credenciales |
| Comunicaciones | Informa al personal, a los pacientes y, cuando corresponda, al regulador; una sola voz |
| Dueño del negocio | Acepta la pérdida de datos, aprueba la vuelta al servicio |

La escalada va por rol: DBA de guardia → comandante del incidente → responsable de seguridad y dueño del negocio.
Los datos de contacto están en la herramienta de guardias, no en este documento.

## 3. Puntos de decisión

- **D1 — ¿Los datos son accesibles y confiables?** Tras un ransomware, se asume que **no**: ni los servidores de
  bases de datos ni el recurso de copias. No se intenta repararlos en el sitio.
- **D2 — ¿Restaurar en el sitio o en hosts limpios?** Siempre en **hosts limpios** tras un compromiso. Los servidores
  viejos son evidencia y pueden contener aún las herramientas del atacante.
- **D3 — ¿Cuál es el último punto de restauración seguro?** La copia más reciente **escrita antes de T0**, donde T0
  es el inicio de la actividad maliciosa. Lo fija el responsable de seguridad; si el atacante estaba dentro antes del
  cifrado, T0 retrocede a la primera acción maliciosa, y con él el punto de restauración. "La copia más reciente" no
  es segura por defecto: todo lo escrito después de T0 puede ser del atacante. La herramienta lo hace cumplir: solo
  lee versiones de objetos que el almacenamiento escribió antes de T0, descarga cada copia por su id de versión y
  rechaza cualquier checksum que no coincida.
- **D4 — ¿Cuándo volver al servicio?** Cuando la restauración pasó la verificación (chequeo de consistencia, conteo
  de filas, continuidad de los datos), el dueño del negocio aceptó la pérdida de datos medida y se rotaron las
  credenciales que el atacante pudo tener (administradores de bases de datos, clave de escritura de copias).

## 4. Procedimiento — SQL Server (`appointments`)

1. Registrar la hora en que se declara la recuperación (`drkit mark --facts out/drill/facts.json declared_at=now`
   en el simulacro).
2. Obtener la cadena de restauración solo del nivel externo, con el T0 de D3:
   ```bash
   drkit fetch --policy policy/dr-policy.yaml --system appointments --before <T0> --dest out/restore/mssql
   ```
   Selecciona la copia completa más reciente, la diferencial más reciente posterior y cada copia de log posterior,
   comprueba que no falte ninguna copia de log, descarga cada archivo por id de versión, verifica su SHA-256 y
   escribe `restore.sql`. Un hueco o un checksum que no coincide se detiene aquí con un error — nunca una
   restauración más corta.
3. En el SQL Server limpio, ejecutar el script generado (completa y diferencial `WITH NORECOVERY`, cada log
   `WITH NORECOVERY` y luego `RESTORE DATABASE … WITH RECOVERY`):
   ```bash
   sqlcmd -C -b -S localhost -U sa -i /restore/restore.sql
   ```
4. Verificar: `DBCC CHECKDB([appointments]) WITH NO_INFOMSGS` debe salir limpio; `lab/mssql/verify.sql` devuelve la
   hora de la fila más reciente, el número de filas y el primer y último número de secuencia (las filas deben ser
   contiguas).
5. Registrar la hora en que pasó la verificación (`recovered_at`). Ahí termina el RTO.

## 5. Procedimiento — PostgreSQL (`billing`)

1. Obtener la copia base y el WAL archivado escritos antes de T0:
   ```bash
   drkit fetch --policy policy/dr-policy.yaml --system billing --before <T0> --dest out/restore/pg
   ```
   Los segmentos de WAL deben ser contiguos desde el segmento en que empieza la copia base; si falta uno, se detiene
   aquí.
2. En el PostgreSQL limpio, como usuario `postgres`: crear un directorio de datos vacío, extraer `base.tar` y el
   `base.tar.gz` que contiene, añadir `restore_command = 'gunzip -c /restore/wal/%f.gz > %p'` a
   `postgresql.auto.conf`, crear `recovery.signal` e iniciar el servidor con `pg_ctl -D <dir> -w start`.
   PostgreSQL reproduce cada segmento de WAL que puede obtener y luego se promueve (`SELECT pg_is_in_recovery()`
   devuelve `f`).
3. Verificar: `pg_amcheck --install-missing -d billing` debe salir limpio; `lab/pg/verify.sql` devuelve la hora de la
   fila más reciente, el número de filas y el primer y último número de secuencia. La recuperación se detiene en el
   primer segmento que no puede obtener y se promueve igual, así que también hay que comprobar hasta dónde llegó:
   `SELECT pg_walfile_name(pg_last_wal_replay_lsn())` debe nombrar el último segmento obtenido (si no, `drkit report`
   da la restauración por fallida).
4. Registrar `recovered_at`.

## 6. Medir el resultado

- **RPO logrado** = T0 − la hora de la fila más reciente presente en la base restaurada: los datos realmente
  perdidos, leídos de los datos, no del calendario de copias.
- **RTO logrado** = `recovered_at` − `declared_at`, tiempo de reloj, incluidas la descarga, el checksum, la
  restauración y las verificaciones.
- `drkit report` escribe ambos frente a los objetivos, más lo que el atacante intentó en el nivel externo;
  `drkit gate` falla si se incumple un objetivo, si una restauración no se verifica o si se perdió una versión
  externa.

**Tiempo comprimido en el simulacro.** El simulacro reproduce el calendario con un minuto de política por segundo
real, así que un tramo de 400 minutos (una copia completa, una diferencial y 26 copias de log) dura unos siete
minutos. El RPO logrado se convierte de nuevo a minutos de política para compararlo con el objetivo; el RTO no se
comprime: las restauraciones tardan lo que tardan.

## 7. Después de la recuperación

- Rotar la clave de escritura de copias y todas las credenciales de administración de bases de datos.
- Conservar la evidencia: el registro del ataque (`attack.json`), la lista de versiones previa al ataque, el
  manifiesto usado y los discos de los servidores viejos.
- Hacer una revisión posterior (hot wash) en menos de una semana (plantilla en
  `docs/tabletop-ransomware.es.md`) y actualizar este runbook.
