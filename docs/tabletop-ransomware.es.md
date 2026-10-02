# Ejercicio de mesa — ransomware en el servidor de bases de datos

> Un ejercicio escrito; no se ha realizado con personas. El simulacro de CI es su mitad técnica: ejecuta el ataque y
> la recuperación descritos aquí y los mide.

## Escenario

Viernes, 22:40. El sistema de citas de la clínica deja de responder. El DBA de guardia encuentra que la base
`appointments` ya no está en el SQL Server y un archivo llamado `README-RANSOM.txt` en el recurso de copias. El
servidor PostgreSQL del sistema de facturación tampoco responde.

## Objetivos

1. Decidir rápido que el entorno no es confiable y recuperar en hosts limpios.
2. Elegir el último punto de restauración *seguro* en lugar de la copia más reciente.
3. Recuperar dentro de los objetivos: `appointments` RPO ≤ 15 min, RTO ≤ 30 min; `billing` RPO ≤ 5 min,
   RTO ≤ 60 min.
4. Mantener comunicaciones coherentes y decisiones registradas.

## Participantes

Facilitador, comandante del incidente, DBA de guardia, responsable de seguridad, comunicaciones, dueño del negocio
(roles como en `docs/runbook.es.md`).

## Eventos (injects)

| Hora | Evento | Decisión esperada | Runbook |
|---|---|---|---|
| 22:40 | Detección: base de datos eliminada, nota de rescate en el recurso de copias | Declarar un incidente mayor; el comandante del incidente lleva la línea de tiempo; nadie toca los servidores más allá de aislarlos | §2, D1 |
| 23:00 | El recurso de copias también está cifrado; las copias locales se perdieron | La recuperación vendrá del nivel externo; confirmar que sus versiones están intactas (borrados rechazados en los registros del almacenamiento) | §1, D1 |
| 23:20 | Correo de extorsión: pagar o se publicarán datos de pacientes | El responsable de seguridad y el dueño del negocio lo tratan aparte de la recuperación; comunicaciones prepara la notificación; ningún contacto con el atacante sin asesoría legal; ninguna decisión de pago bajo presión de tiempo | §2, §7 |
| 23:45 | El negocio quiere restaurar "ya" la copia más reciente | El responsable de seguridad fija T0 con la evidencia; se restaura la copia más reciente **escrita antes de T0**, en hosts limpios | D2, D3 |
| 01:30 | Restauraciones terminadas — ¿se reconectan las aplicaciones? | Solo después de pasar la verificación, de que el dueño del negocio acepte la pérdida de datos medida y de rotar las credenciales | D4, §6, §7 |

## Notas para el facilitador

Cómo se ve lo bien hecho: aislar antes de investigar; un único registro de decisiones; recuperación en hosts
limpios; T0 fijado por el responsable de seguridad, no por quien tenga más prisa; RPO y RTO medidos, no estimados;
credenciales rotadas antes de reconectar.

Errores comunes que conviene explorar:

- Restaurar en el servidor comprometido "porque es más rápido".
- Confiar en la copia más reciente sin preguntar cuándo entró el atacante.
- Suponer que el recurso de copias está a salvo porque es "otro servidor".
- Tratar el pago como una opción de recuperación; no devuelve la confianza en los sistemas.
- Varias personas hablando con el personal y los pacientes con mensajes distintos.

## Revisión posterior (plantilla)

| Pregunta | Notas | Responsable | Fecha |
|---|---|---|---|
| ¿Qué salió bien? | | | |
| ¿Qué nos frenó? | | | |
| ¿Qué decisión fue la más difícil y qué información faltó? | | | |
| ¿Qué cambia en el runbook? | | | |
| ¿Qué cambia en las copias o en su protección? | | | |
