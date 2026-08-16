# OMEN AI Cluster
### Infraestructura local para razonamiento distribuido, agentes autónomos y conocimiento persistente

> **En una frase:** una infraestructura que corre en tu propio hardware, coordina varios modelos de IA especializados como si fueran un único sistema inteligente, itera sobre sus propias respuestas hasta afinarlas, y decide por sí misma cuándo resolver algo en local y cuándo apoyarse en la nube.

---

## Resumen ejecutivo

OMEN AI Cluster es una infraestructura de IA autoalojada, modular y reproducible, diseñada para orquestar distintos modelos de lenguaje, asignarles roles especializados, combinar sus resultados y conservar el conocimiento generado como un activo reutilizable. No es una llamada aislada a un modelo: es una arquitectura de razonamiento distribuido, construida en capas, donde los modelos ejecutan tareas, los agentes coordinan tareas, y una capa superior de orquestadores coordina a los propios agentes.

Todo corre en contenedores Docker sobre Ubuntu, con aceleración GPU NVIDIA, y con más de 150 commits documentando cada iteración real del sistema. Es un proyecto open source que desarrollo en solitario, y el patrocinio que busco tiene un objetivo muy concreto: **acceso a modelos de IA de pago en la nube, vía API**, para poder terminar de construirlo.

---

## El problema

Gran parte del potencial de la IA sigue concentrado en servicios centralizados y costosos. Para estudiantes, desarrolladores independientes y equipos pequeños, acceder de forma continuada a modelos avanzados se convierte rápidamente en una barrera económica, técnica y de privacidad. Además, un único modelo rara vez es la mejor herramienta para todo: razonar, programar, investigar y responder rápido son trabajos distintos, y casi ninguna configuración local de IA acumula conocimiento entre sesiones ni orquesta nada más allá de un simple chat.

OMEN AI Cluster parte de una idea sencilla: **la inteligencia no tiene por qué residir en un único modelo — puede emerger de la coordinación de varios modelos especializados.**

---

## La arquitectura: seis capas de razonamiento

```
┌────────────────────────────────────────────────────┐
│  CAPA 6 · Fusión híbrida local + nube   (roadmap)   │
│  Combina modelos propios con modelos cloud vía API  │
├────────────────────────────────────────────────────┤
│  CAPA 5 · Agentes que orquestan agentes             │
│  Planifica, ejecuta, valida, reintenta, consolida   │
├────────────────────────────────────────────────────┤
│  CAPA 4 · Agentes especializados                    │
│  @coder · @analyst · @reasoner · @researcher        │
├────────────────────────────────────────────────────┤
│  CAPA 3 · Conocimiento local persistente            │
│  Vault propio + base vectorial (RAG)                │
├────────────────────────────────────────────────────┤
│  CAPA 2 · Routing inteligente                       │
│  Interfaz común entre modelos + gestión de VRAM     │
├────────────────────────────────────────────────────┤
│  CAPA 1 · Modelos especializados                    │
│  Varios motores de inferencia, cada uno con un rol  │
└────────────────────────────────────────────────────┘
```

**Capa 1 — Modelos especializados.** El clúster combina varios motores de inferencia local (Ollama, TabbyAPI/ExLlamaV2, SGLang), cada uno sirviendo modelos con un perfil distinto: mayor capacidad para análisis complejo, modelos ligeros para respuesta rápida, y modelos dedicados a programación.

**Capa 2 — Routing inteligente.** Por encima de los motores existe una capa de abstracción que evita que el resto del sistema tenga que conocer las particularidades de cada backend: una interfaz común permite referirse a los modelos mediante alias lógicos, mientras que un mecanismo de gestión dinámica decide qué modelo ocupa la GPU en cada momento cuando la VRAM disponible no permite mantenerlos todos cargados a la vez.

**Capa 3 — Conocimiento local persistente.** El sistema no trabaja solo con lo que sabe el modelo: mantiene una base de conocimiento propia (un vault indexado en una base vectorial) que se consulta durante el razonamiento y se enriquece con lo que el propio sistema va generando. Documentación, decisiones de arquitectura, errores y soluciones se acumulan como contexto reutilizable para tareas futuras, en lugar de perderse al cerrar la sesión.

**Capa 4 — Agentes especializados.** Sobre el routing de modelos se construye una capa de agentes con roles delegados: uno investiga, otro programa, otro razona, otro cuestiona y valida resultados. El diseño contempla integrar herramientas como ciclos iterativos de edición de código sobre repositorios reales y flujos de debate multiagente conectados al conocimiento local, para pasar de *modelo → respuesta* a *tarea → planificación → agentes → modelos → resultado → crítica → nueva iteración → validación*.

**Capa 5 — Agentes que orquestan agentes.** Esta es la parte más ambiciosa, y ya no es solo diseño: el clúster expone una API real de tareas agénticas —creación, seguimiento por streaming, cancelación y métricas de éxito/fallo— que implementa exactamente este paradigma: una capa superior decide qué agentes participan, los agentes deciden qué modelos necesitan, los resultados suben de nivel, y el orquestador decide si el resultado es suficientemente bueno o si hace falta una nueva iteración.

**Capa 6 — Fusión híbrida local + nube.** La capa que corona la arquitectura, y la que está en el centro de esta propuesta de patrocinio: permitir que el orquestador decida, tarea a tarea, qué resolver en local y qué merece la pena enviar a un modelo cloud — combinando la privacidad y el coste cero de lo local con la potencia puntual de los modelos de frontera, sin depender en exclusiva de ninguno de los dos mundos.

---

## La iteración como principio de calidad

La mayoría de sistemas de IA plantean una interacción directa: *pregunta → modelo → respuesta*. OMEN AI Cluster plantea otra cosa: *problema → análisis → planificación → ejecución → evaluación → corrección → nueva ejecución → validación → consolidación*.

Un agente puede generar una solución; otro puede intentar encontrar sus errores; un tercero puede compararla con el conocimiento ya almacenado; y el sistema puede volver a ejecutar la tarea incorporando ese feedback antes de dar la respuesta por buena. El objetivo es convertir la inferencia en un proceso verificable e iterativo, no en el resultado de una única generación.

---

## Por qué esta base técnica

- **Ubuntu** como sistema base: el ecosistema con mejor soporte para desarrollo, automatización, Docker y computación GPU, sin saturar recursos que deben quedar libres para la inferencia — y, además, abierto y alineado con la filosofía open source del proyecto.
- **Docker** para que motores, base vectorial, buscador y orquestador se desplieguen igual en cualquier máquina nueva, sin reconfiguración manual.
- **GPU NVIDIA** como acelerador central. El clúster corre hoy sobre una única RTX 4070 de 8 GB de VRAM, lo que ha obligado a resolver en la práctica un problema muy real: gestionar dinámicamente qué modelo ocupa esa memoria limitada para que varios motores no compitan entre sí. El objetivo nunca ha sido tener el ordenador más potente, sino extraer el máximo valor posible de cada unidad de hardware disponible.

---

## Estado actual — un sistema en producción diaria, no un prototipo

- Script de arranque versionado (decenas de iteraciones) que levanta el clúster completo en un solo comando, con modos de arranque, parada, reindexado y estado en tiempo real.
- Router propio, también versionado, con endpoints de salud y métricas.
- API real de tareas agénticas ya funcionando: creación de tareas con número de iteraciones configurable, seguimiento del estado, streaming de progreso y cancelación — con métricas propias de tareas completadas, fallidas y activas.
- Retos de ingeniería reales ya resueltos en producción, no en teoría: contención de VRAM entre modelos simultáneos, bloqueos en el loop async del servidor, incompatibilidades de imágenes Docker, fallos silenciosos de configuración.
- Más de 150 commits documentando cada iteración de la arquitectura.

---

## Desarrollo de software como banco de pruebas

Aunque la arquitectura puede aplicarse a muchos dominios, uno de los primeros usos reales es el desarrollo de software asistido por IA: un entorno exigente para poner a prueba la orquestación completa, desde analizar un repositorio hasta modificar código, ejecutar pruebas y volver a iterar sobre el resultado. Es también el terreno natural del propio autor del proyecto, lo que convierte cada mejora de la arquitectura en algo que se usa y se valida a diario, no solo se diseña.

Ese banco de pruebas permite investigar preguntas muy concretas: cuánto mejora un resultado cuando otro modelo actúa como crítico, cuántas iteraciones adicionales compensan su coste computacional, o qué tareas conviene resolver en local frente a delegarlas a la nube.

---

## Para qué se destinaría el patrocinio

El patrocinio que busco no es de hardware ni de infraestructura: es **acceso a modelos de IA de pago en la nube, a través de sus APIs.** Ese acceso cumple dos funciones muy concretas en el desarrollo de OMEN AI Cluster:

**1. Como apoyo directo al desarrollo.** Este es un proyecto que llevo adelante en solitario, y hay funciones ambiciosas del roadmap —sobre todo en las capas de agentes y orquestación— a las que me cuesta llegar solo. Poder apoyarme en modelos de IA de frontera durante el propio proceso de desarrollo (programando, revisando, depurando, ayudándome a resolver partes concretas de la arquitectura) es lo que me permitiría terminar de completar esas funciones pendientes y dar por cerrada la aplicación open source.

**2. Como parte del propio producto.** La Capa 6 —la fusión híbrida entre modelos locales y modelos en la nube— es una funcionalidad central del proyecto, no un añadido. Para construirla y validarla de verdad necesito poder ejecutar esos modelos cloud de forma continuada: comparar resultados, medir cuándo conviene delegar una tarea a la nube frente a resolverla en local, y comprobar que la integración funciona con datos reales.

En resumen: el patrocinio se traduce directamente en crédito de API de proveedores de modelos en la nube. Es el único recurso que necesito para seguir avanzando y terminar de sacar adelante el proyecto.

---

## Por qué patrocinar este proyecto

Existe una oportunidad clara entre dos mundos: por un lado, los grandes proveedores de IA, con enormes capacidades pero modelos de negocio centrados en infraestructura cloud; por otro, millones de desarrolladores, estudiantes y equipos pequeños con recursos limitados que necesitan herramientas inteligentes, privadas y asequibles. OMEN AI Cluster construye un puente entre ambos mundos, y lo hace de forma abierta:

- **Efecto multiplicador de código abierto:** cada mejora en la orquestación local queda disponible para cualquiera que quiera montar su propio clúster sin el presupuesto de una empresa.
- **Banco de pruebas real:** es un entorno de uso diario, no un benchmark sintético — cualquier modelo cloud que se integre se valida contra una carga de trabajo genuina, no contra un demo.
- **Democratizar la orquestación de IA:** el proyecto nace precisamente de no tener grandes fondos para experimentar; el objetivo es acortar ese mismo camino para quien lo intente después.

---

## Qué puede recibir un patrocinador

- Mención y enlace visible en el repositorio y en la documentación del proyecto.
- Acceso anticipado a nuevas capas y funcionalidades a medida que se completan.
- Voz directa en la priorización del roadmap.
- Un caso de uso real y público de sus modelos integrados en un sistema híbrido local+nube en producción diaria — no en un demo aislado.

*(Contraprestaciones de partida, ajustables según el tipo de patrocinio.)*

---

## Sobre el autor

Detrás del proyecto hay un ingeniero con formación en automatización y control industrial, actualmente ampliando esa base con programación de sistemas (C/C++) en 42 Barcelona. OMEN AI Cluster nace de ese cruce: años de experiencia llevando sistemas a producción, aplicados ahora a construir infraestructura de IA propia, abierta y reproducible — un proyecto que necesita el respaldo de la propia IA para terminar de completarse.

---

## Cierre

> No busco construir otro chatbot. Busco construir una infraestructura capaz de coordinar inteligencias — donde los modelos sean componentes intercambiables, los agentes estén especializados, el conocimiento sea persistente, los resultados puedan criticarse, los errores provoquen nuevas iteraciones, y lo local y la nube colaboren en lugar de competir.

## Repositorio

**https://github.com/felipecela/ia_models**
