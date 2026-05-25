# =============================================================================
# CASOS DE PRUEBA REGULATORIOS — RAG aiquaa_rag
# Generado: 2026-05-25
# Fuente: BCP (Banco Central del Paraguay) + CONATEL
# Modo: búsqueda semántica sobre 19.236 chunks embebidos
# =============================================================================

# =============================================================================
# CASO 1 — Transferencias SIPAP/SPI 24/7
# Regulación: Resolución N°1 Acta N°26 (17.05.2022) — Reglamento SIPAP
#             Resolución N°1 Acta N°35 (11.07.2023) — Reglamento Gral. Sistemas de Pagos
# =============================================================================

Feature: Transferencias SIPAP/SPI disponibles 24x7

  Como cliente de una entidad financiera participante del SIPAP
  Quiero realizar transferencias SPI en cualquier momento del día
  Para cumplir con el Reglamento General de los Sistemas de Pagos del Paraguay (BCP)

  Background:
    Given la entidad es participante habilitado del SIPAP
    And el sistema tiene integración activa con el SPI del BCP
    And la normativa aplicable es la Resolución N°1 Acta N°35 de fecha 11.07.2023

  Scenario: Transferencia SPI exitosa en horario bancario normal
    Given el cliente tiene saldo suficiente en cuenta
    And el monto de transferencia es G. 500.000
    And el horario es un día hábil entre 08:00 y 17:00
    When el cliente inicia una transferencia SPI
    Then el sistema procesa la transferencia en tiempo real
    And el beneficiario recibe acreditación en la cuenta en menos de 15 segundos
    And se genera comprobante con número de operación SPI

  Scenario: Transferencia SPI disponible un sábado a las 23:00
    Given el cliente tiene saldo suficiente en cuenta
    And el monto de transferencia es G. 1
    And el horario es sábado 23:00 (fuera de horario LBTR/ACH)
    When el cliente inicia una transferencia SPI
    Then el sistema NO rechaza la operación por horario
    And el SPI procesa la transferencia ya que funciona 24/7 los 7 días de la semana
    And el beneficiario recibe los fondos dentro del plazo normativo

  Scenario: Transferencia SPI disponible en feriado nacional
    Given el cliente tiene saldo suficiente en cuenta
    And la fecha es un feriado nacional
    When el cliente inicia una transferencia SPI
    Then el sistema acepta y procesa la operación
    And el sistema registra el día como hábil para SPI conforme Art. 3.07 del Reglamento

  Scenario Outline: Rango de montos permitidos para SPI
    Given el cliente tiene saldo suficiente
    When el cliente transfiere <monto> guaraníes vía SPI
    Then el sistema <resultado> la transferencia
    And se registra el monto en el log de operaciones

    Examples:
      | monto        | resultado |
      | 1            | acepta    |
      | 1.000.000    | acepta    |
      | 50.000.000   | acepta    |

  Scenario: El sistema NO puede enviar transacciones LBTR/ACH fuera de horario
    Given el horario es sábado 15:00 (fuera del horario operativo LBTR)
    When el cliente intenta una transferencia LBTR (no SPI)
    Then el sistema rechaza la operación indicando horario no disponible para LBTR
    And sugiere al cliente usar la vía SPI disponible 24/7


# =============================================================================
# CASO 2 — Autenticación de Doble Factor (2FA/OTP)
# Regulación: Circular G.G. N°1 de fecha 07.03.2025 — Medidas Mitigación Riesgo Fraude
#             Resolución N°7 Acta 10 (14.03.2024) — Manual de Seguridad para Entidades
#             Resolución N°16 Acta N°18 (02.05.2024)
# =============================================================================

Feature: Autenticación de doble factor para operaciones vía canales digitales

  Como entidad financiera con canales digitales (home banking / app)
  Quiero implementar OTP obligatorio para transacciones SIPAP
  Para cumplir la Circular G.G. N°1/2025 del BCP

  Background:
    Given la entidad cuenta con canal digital (sitio web, home banking o app)
    And la normativa aplicable es la Circular G.G. N°1 de fecha 07.03.2025
    And la entidad es participante del SIPAP

  Scenario: OTP requerido para transferencia SIPAP independientemente del monto
    Given el cliente está autenticado en home banking
    And el cliente desea realizar una transferencia vía SIPAP de G. 10.000
    When el cliente confirma la operación
    Then el sistema solicita un código OTP antes de procesar
    And la transferencia NO se ejecuta sin validación OTP exitosa

  Scenario: OTP requerido para transferencia SIPAP de monto mínimo (G. 1)
    Given el cliente está autenticado en la app móvil
    And el monto de la transferencia es G. 1
    When el cliente confirma la transferencia vía SIPAP
    Then el sistema exige OTP sin excepción por monto bajo
    And la Circular G.G. N°1/2025 establece OTP sin importar el monto

  Scenario: OTP bloqueado al tercer intento fallido
    Given el cliente recibió un OTP válido
    When el cliente ingresa el OTP incorrecto 3 veces consecutivas
    Then el sistema bloquea la operación
    And notifica al cliente sobre el bloqueo por seguridad
    And genera alerta interna de posible intento de fraude

  Scenario: OTP con tiempo de expiración
    Given el sistema generó un OTP para el cliente
    When han transcurrido más de 5 minutos desde la generación del OTP
    Then el OTP es inválido
    And el sistema solicita generar un nuevo OTP

  Scenario: El sistema detecta transacción sospechosa y la bloquea preventivamente
    Given el sistema de monitoreo antifraude está activo
    And se detecta un patrón de operación inusual para el cliente
    When el cliente intenta ejecutar la transferencia
    Then el sistema bloquea la transacción para revisión
    And genera un reporte de operación sospechosa conforme a la Circular G.G. N°1/2025
    And remite informe a la Superintendencia de Bancos si corresponde


# =============================================================================
# CASO 3 — Apertura de Cuenta 100% Digital
# Regulación: Resolución N°5, Acta N°13 de fecha 04.04.2024
#             Reglamento de las Cuentas Básicas de Ahorro — BCP
# =============================================================================

Feature: Apertura digital de cuentas básicas de ahorro

  Como persona física sin cuenta bancaria
  Quiero abrir una cuenta básica de ahorro de forma remota
  Para acceder a servicios financieros sin presencia física
  Conforme a la Resolución N°5 Acta N°13 del 04.04.2024 (BCP)

  Background:
    Given la entidad supervisada ofrece el producto "cuenta básica de ahorro"
    And el modelo de contrato fue aprobado previamente por la Superintendencia de Bancos
    And el canal digital de apertura remota está habilitado

  Scenario: Apertura exitosa con documento de identidad válido
    Given el cliente es una persona física
    And el cliente presenta su cédula de identidad vigente
    And el cliente no posee otra cuenta básica en la misma entidad
    When el cliente completa el formulario de apertura digital
    And acepta los términos del contrato expuestos en el canal digital
    Then la cuenta básica de ahorro es creada exitosamente
    And la cuenta queda habilitada en moneda local (Guaraníes)
    And se genera constancia de apertura remota

  Scenario: Sistema rechaza apertura si el cliente ya tiene cuenta básica en la misma entidad
    Given el cliente ya posee una cuenta básica de ahorro activa en la entidad
    When el cliente intenta abrir una segunda cuenta básica
    Then el sistema rechaza la apertura con mensaje claro
    And indica que solo se permite una cuenta básica por persona por entidad (Art. 3 Res. N°5/2024)

  Scenario: Verificación de identidad obligatoria antes de activar la cuenta
    Given el cliente completó el formulario de apertura digital
    When el proceso de validación de identidad biométrica falla
    Then la cuenta NO es habilitada
    And el sistema informa al cliente que debe reintentar la verificación
    And registra el intento fallido en log de seguridad

  Scenario: Contrato debe ser mostrado antes de confirmar apertura
    Given el cliente accede al flujo de apertura digital
    When el sistema presenta los términos y condiciones del contrato
    Then el cliente debe aceptar explícitamente los términos antes de continuar
    And el sistema registra fecha y hora de aceptación
    And la aceptación es válida como firma electrónica conforme a Ley N°4017/10

  Scenario: Apertura no puede estar condicionada a otros productos
    Given el cliente completa el proceso de apertura de cuenta básica
    When el sistema intenta asociar obligatoriamente otro producto financiero
    Then el sistema NO debe bloquear la apertura si el cliente rechaza el producto adicional
    And la apertura de cuenta básica es independiente de cualquier otro producto (Art. 21 Res. N°5/2024)

  Scenario: La cuenta puede ser cerrada de forma remota si tiene saldo cero y sin movimientos
    Given la cuenta básica tiene saldo cero
    And no registra movimientos en los últimos 12 meses
    When la entidad ejecuta el proceso de cierre automático
    Then la cuenta es cerrada conforme al Art. 15 de la Resolución N°5/2024
    And se notifica al cliente por el canal digital


# =============================================================================
# CASO 4 — Score de Riesgo Crediticio
# Regulación: Resolución N°1 Acta N°74 (08.09.2008) — Pautas Básicas Gestión Riesgo Crédito
#             Resolución N°16 Acta N°78 (24.11.2010)
#             Resolución N°6 Acta N°77 (20.11.2018)
#             Resolución N°8 Acta N°78 (22.11.2018)
# =============================================================================

Feature: Cálculo de score de riesgo crediticio previo a aprobación

  Como entidad financiera supervisada por el BCP
  Quiero evaluar el riesgo crediticio del solicitante antes de aprobar créditos
  Para cumplir las Pautas Básicas de Gestión del Riesgo de Crédito (Res. N°1/2008)

  Background:
    Given el sistema tiene acceso al historial crediticio del cliente
    And los umbrales de aprobación están definidos y documentados por el Directorio
    And existe una Unidad de Análisis de Riesgos operativa

  Scenario: Score calculado considera historial crediticio, cuota/ingreso y garantías
    Given el cliente solicita un crédito de consumo
    When el sistema calcula el score de riesgo crediticio
    Then el cálculo incluye el historial crediticio del cliente
    And incluye la relación cuota/ingreso del solicitante
    And valida que las garantías ofrecidas cubren adecuadamente el riesgo
    And el resultado queda documentado en el expediente de crédito

  Scenario: Crédito que supera límite preestablecido debe ser reportado al área correspondiente
    Given el cliente solicita un crédito hipotecario por encima del límite preestablecido
    When el sistema evalúa la solicitud
    Then el sistema reporta automáticamente al área supervisora correspondiente
    And el desembolso requiere aprobación en el nivel jerárquico autorizado (Art. 15 Res. N°1/2008)

  Scenario: Crédito con categoría de riesgo ALTO requiere medidas de mitigación documentadas
    Given el sistema calcula un score de riesgo ALTO (categoría A) para el solicitante
    When el Comité de Crédito revisa la solicitud
    Then se identifican y documentan las medidas de mitigación de riesgo
    And la aprobación requiere autorización del nivel jerárquico correspondiente
    And queda registro del análisis A&S conforme a Resolución N°8 Acta N°78/2018

  Scenario: Sistema rechaza crédito si relación cuota/ingreso supera límite regulatorio
    Given el cliente tiene ingresos mensuales de G. 5.000.000
    And la cuota mensual del crédito solicitado sería G. 3.000.000
    When el sistema calcula la relación cuota/ingreso (60%)
    Then el sistema marca la solicitud como riesgo elevado
    And requiere aprobación manual con justificación documentada

  Scenario: Grupos relacionados deben evaluarse como una sola entidad de riesgo
    Given el solicitante pertenece a un grupo económico relacionado
    When el sistema evalúa el riesgo crediticio
    Then el sistema identifica y consolida la exposición del grupo relacionado
    And calcula el riesgo del grupo como una sola entidad conforme a normativa BCP
    And aplica los límites de concentración correspondientes


# =============================================================================
# CASO 5 — Portabilidad Numérica entre Operadoras Móviles
# Regulación: RD N°1315/2017 (CONATEL) — Portal Reclamos Calidad Telefonía Móvil
#             RD N°2178/2016 — Obligaciones Regulatorias STMC
#             Resolución Directorio N°1019/2019 — Base de Datos Prestadores
#             Resolución Directorio N°1736/2025 (CONATEL)
# =============================================================================

Feature: Gestión de portabilidad numérica entre operadoras móviles

  Como usuario de telefonía móvil en Paraguay
  Quiero conservar mi número al cambiar de operadora
  Para ejercer mi derecho a la portabilidad conforme a la normativa CONATEL

  Background:
    Given el sistema está integrado con el registro de portabilidad de CONATEL
    And la operadora es licenciataria habilitada por la Comisión Nacional de Telecomunicaciones
    And la normativa aplicable incluye regulaciones CONATEL del STMC (Servicio Telefónico Móvil Celular)

  Scenario: Portabilidad completada dentro de las 24 horas
    Given el usuario solicita portabilidad de la operadora A hacia la operadora B
    And el usuario tiene el número activo y sin deudas pendientes
    When la solicitud de portabilidad es registrada en el sistema
    Then la portabilidad debe completarse en menos de 24 horas
    And el usuario conserva el mismo número telefónico en la nueva operadora
    And se genera confirmación de portabilidad exitosa

  Scenario: Sistema rechaza portabilidad si el número tiene deuda pendiente
    Given el usuario solicita portabilidad
    And el número tiene saldo deudor con la operadora origen
    When el sistema valida los requisitos de portabilidad
    Then la solicitud es rechazada con motivo claro
    And se informa al usuario los pasos para regularizar la situación

  Scenario: Créditos remanentes deben ser transferibles o conservados al dar de baja
    Given el usuario tiene créditos prepago remanentes en la operadora origen
    When se completa la portabilidad o baja de línea
    Then el sistema permite al usuario transferir los créditos a otra línea de la misma red
    And si el usuario no ejerce ese derecho, los créditos se mantienen en el registro
    And la operadora reporta mensualmente a CONATEL las líneas dadas de baja con créditos remanentes (RD 923/2014)

  Scenario: Sistema habilita reclamo de calidad de servicio vía portal CONATEL
    Given el usuario experimentó problemas de calidad durante o después de la portabilidad
    When el usuario registra un reclamo en el portal de CONATEL
    Then el sistema asigna un código interno de identificación al reclamo
    And remite el reclamo a la Gerencia de Supervisión y Control de CONATEL vía E-doc
    And notifica a la operadora afectada por correo electrónico (RD N°1315/2017)
    And se hace seguimiento hasta el cierre del reclamo

  Scenario: Cambios en infraestructura de red deben ser autorizados por CONATEL
    Given la operadora planea modificar la configuración de una Estación Radio Base
    When la modificación afecta la cobertura o calidad del STMC
    Then la operadora debe solicitar autorización previa a CONATEL
    And cualquier acuerdo de interconexión con otras operadoras requiere aprobación de CONATEL (RD N°2178/2016)

  Scenario: Base de datos de prestadores debe estar actualizada
    Given la operadora tiene datos registrados en la Base de Datos de Prestadores de CONATEL
    When algún dato del prestador cambia (razón social, dirección, documentos)
    Then la operadora actualiza la información en CONATEL dentro del plazo establecido
    And referencia expresamente que la actualización corresponde a la Base de Datos de Prestadores (RD N°1019/2019)
