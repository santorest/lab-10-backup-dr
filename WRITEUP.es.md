---
title: "Copias de seguridad y recuperación ante desastres con simulacro de ransomware"
id: "lab-10-backup-dr"
category: "Seguridad de bases de datos"
type: "Laboratorio"
status: "en curso"
date: "2026-10-02"
time_to_reproduce: "Una ejecución de CI (fork, activar Actions, ejecutar CI); la duración medida está en los Resultados"
skills: [SQL Server, PostgreSQL, MinIO, S3 Object Lock, Python, boto3, Docker, GitHub Actions]
frameworks: [CIS Controls v8 (11.1, 11.2, 11.3, 11.4, 11.5, 17.4), MITRE ATT&CK (T1486, T1490, T1485)]
repo: "https://github.com/santorest/lab-10-backup-dr"
bundle: "Publicado en el sitio del portafolio con su checksum SHA-256"
---

# Copias de seguridad y recuperación ante desastres con simulacro de ransomware

> **Resumen:** una base SQL Server y una PostgreSQL se respaldan en un recurso local y en un bucket de
> almacenamiento de objetos con Object Lock. Un ransomware simulado elimina ambas bases, borra el recurso y usa la
> clave de copias robada contra el bucket; luego ambas bases se restauran solo desde la copia inmutable en hosts
> limpios, se verifican, y el RPO y el RTO logrados se miden frente a objetivos escritos. Un runbook y un ejercicio de
> mesa lo completan. Todo se ejecuta en GitHub Actions contra contenedores. **Las ejecuciones de CI son reales; los
> datos son sintéticos.**

| | |
|---|---|
| **Rol** | Ingeniero de bases de datos / seguridad responsable de que las bases de una pequeña clínica se puedan recuperar |
| **Entorno** | Repositorio público de GitHub, runners Ubuntu de GitHub, contenedores de SQL Server 2025 y PostgreSQL 18, MinIO (compilación de Chainguard) |
| **Herramientas** | Python 3.12, boto3, copias nativas de SQL Server, `pg_basebackup` + archivado de WAL, `sqlcmd`, `pg_amcheck`, pytest, ruff, mypy, shellcheck, gitleaks |
| **Entregable** | Herramienta de envío de copias y restauración (`drkit`), simulacro de ransomware, RPO/RTO medidos con compuerta, runbook de recuperación y ejercicio de mesa (EN/ES), CI, ruleset de rama, PR de demostración |

---

## 1. Problema

Los operadores de ransomware van primero por las copias de seguridad: una copia que los servidores comprometidos
alcanzan, o que las credenciales de copias robadas pueden borrar, ya no está cuando se necesita. "Tenemos copias" no
es un plan de recuperación; un plan de recuperación dice cuántos datos y cuánto tiempo puede perder el negocio,
mantiene al menos una copia que el atacante no puede destruir y demuestra — con regularidad y con números — que las
bases vuelven dentro de esos límites.

## 2. Diseño

- **Dos niveles.** Las copias nativas llegan a un recurso local (rápido para restaurar, pero alcanzable). Cada
  archivo terminado se envía a un bucket externo con **Object Lock en modo compliance**: hasta la fecha de retención
  nadie puede borrar una versión bloqueada ni acortar su retención — ni la clave de copias ni un administrador.
- **La clave no es la protección.** La clave de escritura de copias tiene permiso para borrar objetos y versiones.
  Si el borrado solo lo impidieran los permisos, quien robara una clave con más privilegios podría hacerlo igual; el
  bloqueo no depende de quién lo pida.
- **Manifiesto con versiones.** Cada archivo enviado queda registrado con su versión de objeto y su SHA-256; el
  manifiesto también se envía y se bloquea. La recuperación descarga cada archivo por versión, así que una
  sobrescritura del atacante (una versión más nueva) o un marcador de borrado no cambian nada.
- **El último punto seguro.** La recuperación solo lee versiones de objetos que el almacenamiento escribió **antes de
  T0**, el inicio del ataque. Todo lo posterior puede ser del atacante.
- **Tiempo comprimido.** El calendario corre a un minuto de política por segundo real. El RPO, que depende del
  intervalo de copias, se mide en segundos reales y se convierte a minutos de política para compararlo; el RTO, que
  depende del trabajo de restauración, no se comprime.

## 3. El simulacro

1. Dos primarios con un escritor cada uno (una fila por segundo: la referencia para medir la pérdida de datos).
2. SQL Server: copia completa en el minuto de política 0, copias de log cada 15 y una diferencial en el 360.
   PostgreSQL: una copia base y archivado continuo de WAL. `drkit ship` copia cada archivo terminado al bucket.
3. En T0 (minuto de política 400) el ransomware detiene el agente de copias, elimina ambas bases, borra el recurso
   local y, con la clave robada, intenta sobre cada versión de objeto: acortar la retención, borrar la versión,
   sobrescribir y borrar.
4. `drkit fetch` arma cada cadena de restauración solo desde el bucket — la completa más reciente, la diferencial
   posterior más reciente y cada log posterior (si falta un número de log, es un error); la copia base y el WAL
   contiguo desde su segmento inicial (si falta un segmento, es un error) —, descarga por id de versión y comprueba
   cada SHA-256.
5. Restauraciones en contenedores limpios, luego `DBCC CHECKDB` / `pg_amcheck` y una comprobación de que las filas
   restauradas son contiguas.

## 4. Medición

- **RPO logrado** = T0 − la fila más reciente de la base restaurada: los datos realmente perdidos, leídos de los
  datos.
- **RTO logrado** = desde "recuperación declarada" hasta "restauración verificada", tiempo de reloj.
- **Compuerta**: falla si se incumple un objetivo, si una restauración no se verifica o si se pierde cualquier
  versión original en el nivel externo.

## 5. Runbook y ejercicio de mesa

El runbook (`docs/runbook.es.md`) define los roles, cuatro puntos de decisión — ¿los datos son confiables?,
¿restaurar en el sitio o en hosts limpios?, ¿cuál es el último punto de restauración *seguro*?, ¿cuándo volver al
servicio? — y los procedimientos por motor con los comandos que ejecuta el simulacro, así que CI ejercita el runbook
en cada ejecución. El ejercicio de mesa (`docs/tabletop-ransomware.es.md`) es un ejercicio escrito con eventos
cronometrados (el recurso de copias también cifrado, extorsión, presión para restaurar la copia más reciente) y las
decisiones esperadas; no se ha realizado con personas.

## 6. Pipeline

| Job | Qué prueba |
|---|---|
| `lint` | ruff, mypy (estricto), shellcheck |
| `unit` | los módulos puros con fixtures y un almacenamiento versionado falso con Object Lock: huecos en la cadena, diferencial obsoleta, versiones posteriores a T0, checksum que no coincide, ataque y supervivencia, límites de RPO/RTO, escapado del reporte; umbral de cobertura del 90 % |
| `drill` | el ciclo completo en ambos motores; artefactos: reporte, registro del ataque, manifiestos, cadenas de restauración, tiempos |
| `secrets` | gitleaks sobre todo el historial |

Se ejecuta en cada pull request, en los push a `main`, cada semana y a demanda. Un ruleset en `main` exige pull
request y los cuatro jobs.

## 7. Resultados

Los resultados se agregan a partir de las primeras ejecuciones de CI.

## 8. Lecciones

- **La herramienta que se pensaba leer cambió.** En PostgreSQL 18, `pg_basebackup -v` con `-X none` ya no imprime
  el punto de inicio del WAL; el propio `backup_manifest` de la copia lo registra (`WAL-Ranges` → `Start-LSN`), así
  que el simulacro lo lee de ahí.
- **Los archivos que escribe un servicio no los puede leer el siguiente.** SQL Server escribe sus copias como `0660`
  a nombre de su propio usuario y PostgreSQL archiva el WAL como `0600`; el proceso de envío en el host no podía leer
  ninguno. Cada copia se escribe en un archivo `.part`, se hace legible y luego se renombra, así el proceso de envío
  nunca ve un archivo a medio escribir o ilegible.
- **La imagen prevista puede desaparecer.** MinIO ya no publica sus propias imágenes de contenedor comunitarias; el
  laboratorio usa una compilación mantenida (Chainguard) fijada por digest.
- **Object Lock se comporta como está documentado, y vale la pena demostrarlo.** Con una clave que puede borrar
  versiones, MinIO rechazó cada borrado de una versión bloqueada ("WORM protected and cannot be overwritten"); un
  borrado simple solo añadió un marcador de borrado encima del original intacto.

## 9. Límites

- Contenedores y datos sintéticos; bases pequeñas, así que los minutos absolutos de RTO no se trasladan a producción.
- Tiempo comprimido para el calendario de copias (el RPO se convierte de nuevo a minutos de política; el RTO no se
  comprime).
- MinIO hace las veces de almacenamiento inmutable en la nube (S3 Object Lock, blobs inmutables de Azure).
- El ejercicio de mesa es escrito, no se realizó con personas.
- No cubierto: gestión de claves de cifrado de copias, copias de máquinas virtuales y servidores de archivos, alta
  disponibilidad.

## 10. Reproducirlo

Haga un fork del repositorio y active Actions: cada push ejecuta el simulacro. En local (Linux, macOS o WSL con
Docker), siga el inicio rápido del README: `bash scripts/run-drill.sh` escribe `out/report.html` y
`out/results.json`.

## 11. Correspondencia

| Marco | Elementos |
|---|---|
| CIS Controls v8 | 11.1 proceso de recuperación de datos, 11.2 copias de seguridad automatizadas, 11.3 proteger los datos de recuperación, 11.4 instancia aislada de los datos de recuperación, 11.5 probar la recuperación de datos, 17.4 proceso de respuesta a incidentes |
| MITRE ATT&CK | T1486 Data Encrypted for Impact, T1490 Inhibit System Recovery (ataques a las copias), T1485 Data Destruction — lo que el simulacro reproduce y de lo que se recupera |
