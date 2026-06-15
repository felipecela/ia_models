Es un miedo completamente lógico. Cuando has invertido horas en descargar decenas de gigabytes de modelos pesados, lo último que quieres es que un comando borre todo por accidente y te toque volver a saturar tu conexión a internet.

Pero aquí hay un detalle técnico crucial sobre la arquitectura que hemos construido que te va a dar mucha tranquilidad: **Eliminar un contenedor de Docker no borra absolutamente nada de lo que has descargado.**

### La regla de oro de Docker: El cascarón vs. El cerebro

Para Docker, existen tres capas completamente independientes:

1. **La Imagen (El programa):** Es el código base (ej. el software de Ollama o ChromaDB). Una vez descargado, se queda guardado en la caché del sistema.
2. **El Volumen (Tus Modelos):** Es tu SSD exFAT (`/home/fcela-ga/sgoinfre/ai_core/models`). Aquí es donde viven los gigabytes reales (Qwen, DeepSeek, etc.).
3. **El Contenedor (El cascarón en ejecución):** Es simplemente un proceso temporal que une la Imagen con tu Volumen.

Por eso tu script `Autoboot_Cluster_V21.sh` ejecuta `docker rm -f` (eliminar contenedor) sin miedo. Al destruir el "cascarón", el puerto se libera instantáneamente, pero tus modelos en el SSD y las imágenes base del sistema quedan intactas. Al crear un contenedor nuevo un segundo después, este simplemente se vuelve a "conectar" a tu SSD y reconoce los modelos en 0 segundos.

Aún así, si prefieres gestionar esto a mano de forma limpia (solo deteniendo los procesos sin destruir los cascarones), esta es la forma correcta de hacerlo.

---

### 1. Detener los contenedores de Docker (Puertos 11434, 11435, 8001, etc.)

El comando `docker stop` le envía una señal de apagado ordenado (SIGTERM) al contenedor, cerrando el puerto y guardando cualquier estado en RAM antes de apagarse.

Puedes detenerlos todos de golpe con este comando:

```bash
docker stop ollama-gpu-main ollama-cpu-router chromadb obsidian-kb searxng

```

*Nota: Si en el futuro quieres volver a encenderlos manualmente sin usar tu script, simplemente cambias `stop` por `start`.*

Si alguna vez quieres detener **todos** los contenedores que estén corriendo en tu máquina (sean del clúster o no) con un solo comando rápido:

```bash
docker stop $(docker ps -q)

```

---

### 2. Detener el Orquestador de Python (Puerto 8000)

Si el router de FastAPI (`orchestrator_router_V14.py`) se quedó corriendo en segundo plano o se quedó "enganchado" ocupando el puerto 8000, Docker no puede detenerlo porque es un proceso nativo de tu sistema operativo.

Para buscar y detener este proceso por su nombre de forma limpia, usa el comando `pkill`:

```bash
pkill -f orchestrator_router_V14.py

```

Si el proceso se niega a morir (algo común si está en medio de una descarga o bloqueado por red), puedes forzar su cierre inmediato (un `kill -9` interno) así:

```bash
pkill -9 -f orchestrator_router_V14.py

```

Al ejecutar el `docker stop` para los contenedores y el `pkill` para Python, todos tus puertos quedarán 100% libres, tu memoria RAM y VRAM se vaciarán, y no habrás perdido ni un solo kilobyte de los modelos que tanto te costó descargar en tu unidad exFAT.
