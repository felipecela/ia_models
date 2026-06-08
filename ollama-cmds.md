Tienes toda la razón. Habíamos mencionado el comando de apagado como una pieza del rompecabezas para evitar conflictos con los contenedores Docker, pero para dominar tu entorno local necesitas el control total del "motor".

En Ubuntu, Ollama se divide en dos capas que debes manejar: **El Servicio del Sistema** (el motor en segundo plano que consume recursos) y **La Interfaz de Comandos CLI** (para descargar, borrar y ejecutar los modelos en tu SSD).

Aquí tienes la guía completa de comandos, estructurada para tu arquitectura.

---

## 1. Gestión del Motor (Systemd)

Estos comandos controlan el proceso general de Ollama. Son vitales para gestionar los 8 GB de VRAM de tu gráfica y evitar que los backends choquen.

* **Ver el estado actual:**
```bash
sudo systemctl status ollama

```


*Para qué sirve:* Te muestra si el motor está encendido, si hay algún error de lectura en tu unidad exFAT, o la ruta exacta donde está buscando los modelos. Para salir de esta vista, pulsa la tecla `q`.
* **Apagar el motor (Liberar hardware):**
```bash
sudo systemctl stop ollama

```


*Para qué sirve:* Descarga cualquier modelo de la memoria RAM y libera el 100% de la VRAM de tu gráfica. **Paso obligatorio** antes de levantar SGLang o ExLlamaV2.
* **Encender el motor:**
```bash
sudo systemctl start ollama

```


*Para qué sirve:* Vuelve a arrancar el servicio. Deberás ejecutarlo después de haber apagado los otros contenedores Docker.
* **Reiniciar el motor:**
```bash
sudo systemctl restart ollama

```


*Para qué sirve:* Muy útil si haces algún cambio en el archivo de configuración (como cambiar la variable `OLLAMA_MODELS`) o si notas que el sistema se ha quedado "congelado".
* **Evitar que arranque automáticamente con Ubuntu:**
```bash
sudo systemctl disable ollama

```


*Para qué sirve:* Por defecto, Ollama se enciende solo al arrancar el ordenador. Si prefieres encenderlo tú manualmente solo cuando vayas a usar OpenClaw u OpenCode, usa este comando. (Para revertirlo, usa `enable`).

---

## 2. Gestión de Modelos (Ollama CLI)

Estos comandos administran los archivos físicos (pesos, tensores) que se guardan en tu carpeta compartida `ai_core/ollama_storage`.

* **Ver los modelos descargados:**
```bash
ollama list

```


*Para qué sirve:* Muestra una tabla con todos los modelos que tienes en el SSD, su tamaño en GB y cuándo se modificaron por última vez.
* **Ver qué se está ejecutando AHORA MISMO (Crítico para la VRAM):**
```bash
ollama ps

```


*Para qué sirve:* Te indica exactamente qué modelo está cargado en este instante, y **lo más importante**: qué porcentaje del modelo está en la VRAM de la gráfica y qué porcentaje se ha desbordado a tus 32 GB de RAM.
* **Descargar un modelo sin ejecutarlo:**
```bash
ollama pull <nombre_del_modelo>

```


*(Ejemplo: `ollama pull deepseek-coder-v2`)*
*Para qué sirve:* Descarga los gigabytes directamente al SSD encriptado. Ideal para dejarlo descargando en segundo plano.
* **Eliminar un modelo (Liberar espacio en el SSD):**
```bash
ollama rm <nombre_del_modelo>

```


*Para qué sirve:* Borra el modelo de la unidad de almacenamiento.

---

## 3. Ejecución e Interacción Básica

Aunque OpenClaw y OpenCode se comunicarán con Ollama de forma invisible mediante su API (puerto 11434), a veces querrás probar un modelo directamente en la terminal.

* **Ejecutar / Chatear con un modelo:**
```bash
ollama run <nombre_del_modelo>

```


*Para qué sirve:* Inicia la carga del modelo en la memoria (verás que tarda unos segundos al leer del disco compartido) y te abre un prompt interactivo.
* **Comandos dentro del chat (Prompt):**
Una vez dentro de `ollama run`, puedes usar comandos especiales escribiendo una barra inclinada `/`:
* `/?` : Muestra el menú de ayuda.
* `/show info` : Te da detalles de la arquitectura del modelo que estás corriendo.
* `/bye` : **Cierra el chat** (aunque el modelo se quedará cargado en la memoria durante 5 minutos por defecto, por si le vuelves a hablar).



Con estos comandos tienes el control absoluto de la capa de Ollama, permitiéndote encender, apagar, limpiar recursos y gestionar tu almacenamiento de forma precisa.
