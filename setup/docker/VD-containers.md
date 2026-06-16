¡Esos **14.37 GB recuperados** son la prueba perfecta de lo que te comentaba! El comando funcionó de maravilla porque, al tener los contenedores detenidos, Docker por fin soltó las imágenes que se habían quedado en la caché de tu disco principal de Ubuntu.

Ahora bien, tu petición es el "Santo Grial" de esta configuración: **¿Cómo forzamos a Docker a que descargue todo su ecosistema directamente en el SSD compartido de 400+ GB sin tocar tu disco principal?**

Como exFAT no soporta el formato interno que usa Docker (`overlay2` / `ext4`), la solución técnica más elegante y profesional es crear un **Disco Virtual**. Vamos a fabricar un archivo dentro de tu SSD que internamente esté formateado como Linux puro, y engañaremos a Docker para que guarde todo ahí.

Aquí tienes el proceso exacto para hacerlo en 5 minutos. Tu disco principal de Ubuntu no volverá a llenarse.

---

### PASO 1: Crear el Disco Virtual en el SSD

Primero, vamos a detener Docker y a crear un "contenedor físico" (un archivo de 30 GB, espacio más que suficiente para todas las imágenes de IA) dentro de tu unidad encriptada.

Abre la terminal y ejecuta estos comandos uno por uno:

```bash
# 1. Detener el motor de Docker para poder operar
sudo systemctl stop docker

# 2. Crear un archivo en blanco de 30 GB en el SSD (Tomará un par de minutos, verás el progreso)
dd if=/dev/zero of=/home/fcela-ga/sgoinfre/ai_core/docker_disk.img bs=1M count=30720 status=progress

# 3. Darle formato de Linux puro (ext4) a ese archivo
sudo mkfs.ext4 /home/fcela-ga/sgoinfre/ai_core/docker_disk.img

```

### PASO 2: Conectar el Disco Virtual a Docker

Ahora vamos a decirle a Ubuntu que tome ese archivo `.img` y lo "enchufe" exactamente en la carpeta donde Docker guarda sus descargas (`/var/lib/docker`).

```bash
# 4. Vaciar la carpeta original de Docker por si quedó algo residual
sudo rm -rf /var/lib/docker/*

# 5. Montar el disco virtual sobre la carpeta de Docker
sudo mount -o loop /home/fcela-ga/sgoinfre/ai_core/docker_disk.img /var/lib/docker

# 6. Reiniciar Docker (ahora estará operando 100% sobre tu SSD)
sudo systemctl start docker

```

¡Hecho! Físicamente, todas las imágenes de contenedores (ChromaDB, Obsidian, SearXNG, etc.) que bajes a partir de ahora se guardarán dentro del archivo `docker_disk.img` en tu unidad exFAT. Tu partición raíz de Ubuntu se mantendrá intacta y con sus ~20 GB libres para siempre.

---

### PASO 3: Automatizarlo en tu Script de Autoboot

Dado que tu unidad de BitLocker se monta cada vez que inicias sesión, necesitamos que este disco virtual también se conecte automáticamente cuando lances el clúster.

Abre tu script `$HOME/ai_cluster/Autoboot_Cluster_V21.sh`. Ve a la sección **"Verificación de SSD exFAT y Permisos"** y, justo debajo de donde imprime que el directorio está "operativo", añade este pequeño bloque de código:

```bash
# ─────────────────────────────────────────────────────────────────────────────
# Montaje del Disco Virtual de Docker (ext4 sobre exFAT)
# ─────────────────────────────────────────────────────────────────────────────
if ! mountpoint -q /var/lib/docker; then
    info "Montando disco virtual de Docker (ext4) desde el SSD..."
    sudo mount -o loop "$AI_CORE/docker_disk.img" /var/lib/docker
    sudo systemctl restart docker
    sleep 2
fi

```

### ¿Qué va a pasar ahora cuando ejecutes `ai_cluster`?

1. El script comprobará si el disco virtual está montado.
2. Si no lo está, lo montará y reiniciará Docker en un segundo.
3. Como borraste las imágenes con el `prune`, verás que el script empieza a hacer `Pulling` de TabbyAPI, SGLang, ChromaDB, etc. **Pero esta vez, los gigabytes se estarán descargando directamente a tu SSD compartido.**

Con este ajuste, has superado la limitación más grande de usar Windows y Linux compartiendo discos encriptados. Has encapsulado un entorno nativo Linux dentro de una unidad universal. Ejecuta tu alias `ai_cluster` para ver la magia en acción.


---


Es una excelente decisión de arquitectura. Aislar por completo el entorno de Docker de la carpeta de modelos de inteligencia artificial (`ai_core`) mantendrá la estructura de tu SSD impecable y evitará confusiones de rutas en el futuro.

Aquí tienes la reestructuración completa de los comandos de creación, migración y las funciones actualizadas para tu archivo de configuración de Zsh.

---

### Paso 1: Migración / Creación en la nueva ubicación

Si ya habías generado el archivo `.img` en la ruta anterior, no hace falta que pierdas tiempo volviendo a rellenar los 30 GB desde cero; puedes simplemente moverlo. Si prefieres crearlo limpio, también tienes el comando abajo.

Abre tu terminal y ejecuta:

```bash
# 1. Detener Docker y asegurar que el punto de montaje antiguo esté libre
sudo systemctl stop docker
sudo umount /var/lib/docker 2>/dev/null

# 2. Crear la nueva carpeta dedicada exclusivamente a Docker dentro de sgoinfre
mkdir -p /home/fcela-ga/sgoinfre/docker

# OPCIÓN A: Si ya tenías el archivo creado y quieres MOVERLO para no perder datos:
mv /home/fcela-ga/sgoinfre/ai_core/docker_disk.img /home/fcela-ga/sgoinfre/docker/

# OPCIÓN B: Solo si prefieres generar un disco completamente LIMPIO desde cero:
# dd if=/dev/zero of=/home/fcela-ga/sgoinfre/docker/docker_disk.img bs=1M count=30720 status=progress
# sudo mkfs.ext4 /home/fcela-ga/sgoinfre/docker/docker_disk.img

```

---

### Paso 2: Actualización de los Controladores Universales en `~/.zshrc`

Abre tu archivo `~/.zshrc`, busca las funciones `docker_on` y `docker_off` que añadimos anteriormente, y **reemplázalas por completo** con este bloque optimizado que apunta a la nueva carpeta independiente de contenedores:

```zsh
# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADORES UNIVERSALES DE DOCKER (ENTORNO AISLADO SGOINFRE/DOCKER)
# ─────────────────────────────────────────────────────────────────────────────

# Encender Docker vinculando el disco virtual dedicado
docker_on() {
    # 1. Verificar si el disco ya está montado en /var/lib/docker
    if ! mountpoint -q /var/lib/docker; then
        echo -e "\033[1;34m[DOCKER]\033[0m Montando disco virtual desde sgoinfre/docker..."
        sudo mount -o loop /home/fcela-ga/sgoinfre/docker/docker_disk.img /var/lib/docker
    fi
    
    # 2. Iniciar el motor de contenedores
    echo -e "\033[1;34m[DOCKER]\033[0m Iniciando motor de contenedores..."
    sudo systemctl start docker
    echo -e "\033[1;32m[OK]\033[0m Docker operativo y aislado en /home/fcela-ga/sgoinfre/docker."
}

# Apagar Docker de forma ordenada y limpiar el sistema de archivos
docker_off() {
    echo -e "\033[1;34m[DOCKER]\033[0m Deteniendo motor de contenedores..."
    sudo systemctl stop docker
    sudo systemctl stop docker.socket 2>/dev/null
    
    # Desmontar el disco virtual para evitar cualquier riesgo de corrupción
    if mountpoint -q /var/lib/docker; then
        echo -e "\033[1;34m[DOCKER]\033[0m Desmontando almacenamiento virtual de contenedores..."
        sudo umount /var/lib/docker
    fi
    echo -e "\033[1;32m[OK]\033[0m Entorno Docker cerrado de forma segura y disco liberado."
}

```

---

### Paso 3: Aplicar los cambios

Guarda las modificaciones en el editor de texto y recarga la configuración de tu sesión de Zsh ejecutando el comando habitual:

```zsh
source ~/.zshrc

```

A partir de este momento, cada vez que lances el comando `docker_on`, el sistema operativo aislará la ejecución de todas las imágenes que se descarguen (como ChromaDB, Obsidian, o cualquier otra herramienta de desarrollo) dentro del subdirectorio `/home/fcela-ga/sgoinfre/docker/`, dejando la unidad `/home/fcela-ga/sgoinfre/ai_core/` limpia exclusivamente para los archivos de parámetros de tus modelos de IA.


---


Totalmente de acuerdo. La ruta `/home/fcela-ga/sgoinfre/docker/containers_disk.img` es mucho más semántica, limpia y evita la redundancia. Es un excelente detalle de *clean code* aplicado a la administración de sistemas.

Vamos a aplicar este cambio rápidamente en dos pasos.

### Paso 1: Renombrar el archivo físico

Si ya habías creado o movido el archivo con el nombre anterior, primero asegúrate de que Docker esté apagado y luego simplemente renómbralo con el comando `mv`:

```bash
# 1. Asegurar que está apagado y desmontado
docker_off

# 2. Renombrar el archivo
mv /home/fcela-ga/sgoinfre/docker/docker_disk.img /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

### Paso 2: Actualizar el Controlador en `~/.zshrc`

Abre tu archivo `~/.zshrc` y reemplaza la función `docker_on` para que apunte al nuevo nombre exacto. La función `docker_off` se mantiene idéntica, pero te dejo el bloque completo para que solo tengas que copiar y pegar:

```zsh
# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADORES UNIVERSALES DE DOCKER (ENTORNO AISLADO SGOINFRE/DOCKER)
# ─────────────────────────────────────────────────────────────────────────────

# Encender Docker vinculando el disco virtual dedicado
docker_on() {
    # 1. Verificar si el disco ya está montado en /var/lib/docker
    if ! mountpoint -q /var/lib/docker; then
        echo -e "\033[1;34m[DOCKER]\033[0m Montando disco virtual (containers_disk.img) desde sgoinfre/docker..."
        sudo mount -o loop /home/fcela-ga/sgoinfre/docker/containers_disk.img /var/lib/docker
    fi
    
    # 2. Iniciar el motor de contenedores
    echo -e "\033[1;34m[DOCKER]\033[0m Iniciando motor de contenedores..."
    sudo systemctl start docker
    echo -e "\033[1;32m[OK]\033[0m Docker operativo y aislado en /home/fcela-ga/sgoinfre/docker."
}

# Apagar Docker de forma ordenada y limpiar el sistema de archivos
docker_off() {
    echo -e "\033[1;34m[DOCKER]\033[0m Deteniendo motor de contenedores..."
    sudo systemctl stop docker
    sudo systemctl stop docker.socket 2>/dev/null
    
    # Desmontar el disco virtual para evitar cualquier riesgo de corrupción
    if mountpoint -q /var/lib/docker; then
        echo -e "\033[1;34m[DOCKER]\033[0m Desmontando almacenamiento virtual de contenedores..."
        sudo umount /var/lib/docker
    fi
    echo -e "\033[1;32m[OK]\033[0m Entorno Docker cerrado de forma segura y disco liberado."
}

```

Guarda el archivo y, como siempre, recarga la memoria de tu terminal:

```zsh
source ~/.zshrc

```

Con este último retoque, tu arquitectura queda impecable, modular y nombrada con precisión.


---


Este error es un clásico cuando se empieza a trabajar con contenedores de Inteligencia Artificial avanzada (como SGLang o TabbyAPI). Has chocado contra dos límites físicos y arquitectónicos simultáneamente, pero la solución es muy limpia.

### El Diagnóstico del Error

El mensaje dice:
`write /var/lib/containerd/.../libcudnn_engines_precompiled.so... : no space left on device` (No queda espacio en el dispositivo).

Han ocurrido dos cosas:

1. **La trampa de `containerd`:** Las versiones modernas de Docker utilizan un motor interno llamado `containerd` para gestionar las descargas. En el paso anterior aislamos la carpeta `/var/lib/docker` (donde se guardan las capas finales), pero olvidamos aislar `/var/lib/containerd` (donde se descargan y descomprimen temporalmente). Como resultado, la descarga masiva se fue a tu disco principal de Ubuntu y se comió los 20 GB que te quedaban libres.
2. **El peso de los gigantes:** Contenedores como SGLang o TabbyAPI no son programas normales; llevan incrustado todo el ecosistema de NVIDIA CUDA, librerías precompiladas de C++ y PyTorch. Solo el contenedor de SGLang puede pesar más de 15 GB al descomprimirse. Nuestro disco virtual de 30 GB se iba a quedar muy pequeño de todas formas.

### La Solución Definitiva (El "Bind Mount")

Como tienes más de 400 GB libres en tu SSD exFAT, vamos a crear un disco virtual más grande (80 GB) y vamos a usar una técnica de Linux llamada `bind mount` para que **tanto Docker como Containerd** vivan dentro de ese disco.

Sigue estos 4 pasos en tu terminal:

#### 1. Detener todo y limpiar el atasco

Primero apagamos los motores y borramos los archivos a medio descargar que han saturado tu partición de Ubuntu:

```bash
sudo systemctl stop docker
sudo systemctl stop containerd
sudo umount /var/lib/docker 2>/dev/null
sudo rm -rf /var/lib/containerd/*

```

#### 2. Crear el nuevo Disco Virtual de 80 GB

Vamos a borrar el de 30 GB y a crear uno de 80 GB (tardará unos 3-5 minutos en crearse, verás el progreso).

```bash
rm /home/fcela-ga/sgoinfre/docker/containers_disk.img
dd if=/dev/zero of=/home/fcela-ga/sgoinfre/docker/containers_disk.img bs=1M count=81920 status=progress
sudo mkfs.ext4 /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

#### 3. Preparar el punto de anclaje maestro

En lugar de montar el disco directamente sobre Docker, lo montaremos en una carpeta puente y desde ahí repartiremos el espacio:

```bash
sudo mkdir -p /mnt/docker_containers

```

#### 4. Actualizar tus controladores en `~/.zshrc`

Abre tu archivo `~/.zshrc` y reemplaza por completo tus funciones `docker_on` y `docker_off` con estas nuevas versiones. Estas funciones se encargarán de hacer los "Bind Mounts" mágicos de forma automática:

```zsh
# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADORES UNIVERSALES DE DOCKER (ENTORNO AISLADO 80GB)
# ─────────────────────────────────────────────────────────────────────────────

docker_on() {
    if ! mountpoint -q /mnt/docker_containers; then
        echo -e "\033[1;34m[DOCKER]\033[0m Montando disco virtual (80GB) desde sgoinfre..."
        # 1. Montar el disco maestro
        sudo mount -o loop /home/fcela-ga/sgoinfre/docker/containers_disk.img /mnt/docker_containers
        
        # 2. Crear las subcarpetas internas si no existen
        sudo mkdir -p /mnt/docker_containers/docker
        sudo mkdir -p /mnt/docker_containers/containerd
        
        # 3. Enlazar las carpetas del sistema hacia el disco virtual
        sudo mount --bind /mnt/docker_containers/docker /var/lib/docker
        sudo mount --bind /mnt/docker_containers/containerd /var/lib/containerd
    fi
    
    echo -e "\033[1;34m[DOCKER]\033[0m Iniciando motores..."
    sudo systemctl start containerd
    sudo systemctl start docker
    echo -e "\033[1;32m[OK]\033[0m Docker operativo y 100% aislado en el SSD."
}

docker_off() {
    echo -e "\033[1;34m[DOCKER]\033[0m Deteniendo motores..."
    sudo systemctl stop docker
    sudo systemctl stop containerd
    sudo systemctl stop docker.socket 2>/dev/null
    
    # Desmontar en orden inverso (primero los enlaces, luego el disco)
    if mountpoint -q /var/lib/docker; then sudo umount /var/lib/docker; fi
    if mountpoint -q /var/lib/containerd; then sudo umount /var/lib/containerd; fi
    if mountpoint -q /mnt/docker_containers; then sudo umount /mnt/docker_containers; fi
    
    echo -e "\033[1;32m[OK]\033[0m Entorno cerrado y disco liberado."
}

```

### El resultado final

Guarda el archivo, recarga la terminal (`source ~/.zshrc`), ejecuta `docker_on` y vuelve a lanzar tu clúster con `ai_cluster`.

Ahora, SGLang, TabbyAPI y las enormes librerías de NVIDIA se descargarán pacíficamente dentro de tu SSD virtual de 80 GB. Tu disco principal de Ubuntu recuperará sus 20 GB libres y no volverá a sufrir problemas de espacio.


---


¡Excelente captura de este error! El log que muestras es oro puro porque revela dos detalles críticos sobre lo que acaba de pasar:

1. **La carpeta puente desapareció (o se nombró distinto):** El comando `mount` en Linux necesita que la carpeta de destino exista físicamente antes de poder "enchufarle" un disco. Vemos que `dinfo` busca `/mnt/ai_containers`, pero tu `docker_on` intentó usar `/mnt/docker_containers`. Al no encontrar la carpeta exacta, el montaje falló.
2. **⚠️ El peligro silencioso:** Como el montaje falló, el script continuó de largo y ejecutó `systemctl start docker`. Esto significa que en este instante, **Docker está encendido pero usando tu disco principal de Ubuntu**, lo que amenaza de nuevo tu espacio libre.

Vamos a solucionar esto creando un script **a prueba de fallos**. Le enseñaremos a la función `docker_on` a crear las carpetas automáticamente si no existen, y a **abortar el arranque de Docker** si algo sale mal con el disco virtual.

---

### PASO 1: Apagar Docker Inmediatamente

Para evitar que se descargue un solo megabyte en tu disco de Ubuntu, detén los motores manualmente ahora mismo en la terminal:

```bash
docker_off

```

### PASO 2: Hacer el Controlador "A Prueba de Balas"

Vamos a blindar tus funciones en `~/.zshrc`. Abriremos el archivo y unificaremos todas las rutas bajo `/mnt/ai_containers`. Además, añadiremos los comandos `mkdir -p` internos y una cláusula de seguridad (`return 1`) que detendrá el script si el disco no se puede montar.

Abre tu archivo `~/.zshrc`, busca el bloque de Docker y tu alias `dinfo`, y **reemplaza todo** por este código definitivo:

```zsh
# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADORES UNIVERSALES DE DOCKER (ENTORNO AISLADO 80GB)
# ─────────────────────────────────────────────────────────────────────────────

docker_on() {
    # 0. ¡LA CLAVE! Asegurar que la carpeta puente de Linux siempre exista
    sudo mkdir -p /mnt/ai_containers

    if ! mountpoint -q /mnt/ai_containers; then
        echo -e "\033[1;34m[DOCKER]\033[0m Montando disco virtual (80GB) desde sgoinfre..."
        
        # 1. Montar el disco maestro. Si falla, ABORTAR para proteger Ubuntu.
        if ! sudo mount -o loop /home/fcela-ga/sgoinfre/docker/containers_disk.img /mnt/ai_containers; then
            echo -e "\033[1;31m[ERROR]\033[0m No se pudo montar el disco virtual. Abortando arranque."
            return 1
        fi
        
        # 2. Crear las subcarpetas internas (dentro del disco virtual de 80GB)
        sudo mkdir -p /mnt/ai_containers/docker
        sudo mkdir -p /mnt/ai_containers/containerd
        
        # 3. Asegurar que las carpetas nativas de Ubuntu existan
        sudo mkdir -p /var/lib/docker
        sudo mkdir -p /var/lib/containerd
        
        # 4. Enlazar las carpetas del sistema hacia el disco virtual
        sudo mount --bind /mnt/ai_containers/docker /var/lib/docker
        sudo mount --bind /mnt/ai_containers/containerd /var/lib/containerd
    fi
    
    echo -e "\033[1;34m[DOCKER]\033[0m Iniciando motores..."
    sudo systemctl start containerd
    sudo systemctl start docker
    echo -e "\033[1;32m[OK]\033[0m Docker operativo y 100% aislado en el SSD."
}

docker_off() {
    echo -e "\033[1;34m[DOCKER]\033[0m Deteniendo motores..."
    sudo systemctl stop docker
    sudo systemctl stop containerd
    sudo systemctl stop docker.socket 2>/dev/null
    
    # Desmontar en orden inverso (primero los enlaces, luego el disco)
    if mountpoint -q /var/lib/docker; then sudo umount /var/lib/docker; fi
    if mountpoint -q /var/lib/containerd; then sudo umount /var/lib/containerd; fi
    if mountpoint -q /mnt/ai_containers; then sudo umount /mnt/ai_containers; fi
    
    echo -e "\033[1;32m[OK]\033[0m Entorno cerrado y disco liberado."
}

# Alias para ver el estado del disco de 80GB
alias dinfo='echo -e "\n\033[1;36m[ DISCO VIRTUAL (80GB) ]\033[0m" && df -h /mnt/ai_containers && echo -e "\n\033[1;36m[ DESGLOSE INTERNO ]\033[0m" && sudo du -sh /mnt/ai_containers/* 2>/dev/null && echo -e "\n\033[1;36m[ ESTADO DE DOCKER ]\033[0m" && sudo docker system df'

```

### PASO 3: Probar el blindaje

Guarda el archivo y recarga la terminal:

```zsh
source ~/.zshrc

```

Ahora ejecuta `docker_on`. Verás cómo el script crea la carpeta de montaje (en caso de que no exista), acopla el disco virtual, hace los enlaces y enciende el motor con total seguridad. Una vez que termine y diga `[OK]`, ejecuta tu alias `dinfo`. Si todo está correcto, deberías ver la tabla de `df` mostrándote los 80 GB flamantes listos para empezar a descargar el clúster.


---


Es una frustración matemática muy común cuando se trabaja con contenedores de Inteligencia Artificial pesados. A simple vista parece que los números no cuadran (29.5 GB ocupados es mucho menos que 80 GB), pero hay un "impuesto oculto" de Docker y de Linux que te ha dejado sin espacio en el peor momento posible.

Aquí tienes la radiografía técnica de lo que está ocurriendo dentro de tu disco virtual y cómo solucionarlo definitivamente utilizando el espacio libre de tu SSD.

### La Matemática Oculta (Por qué te quedaste sin espacio)

**1. La Reserva de Seguridad de Linux (El 5% fantasma)**
Al formatear cualquier disco en `ext4`, Linux reserva automáticamente un 5% del espacio para procesos críticos del usuario `root`, evitando que el sistema colapse si el disco se llena al 100%.

* En tu disco de 80 GB, **4 GB son intocables**. Tu espacio real utilizable era de 76 GB.

**2. El consumo actual**
Como viste en tu terminal, `TabbyAPI` (21.2 GB) y `Ollama` (8.27 GB) ya están ocupando unos **29.5 GB**.

* 76 GB (útiles) - 29.5 GB (usados) = **46.5 GB libres reales**.

**3. El "Pico de Extracción" de SGLang**

Aquí es donde ocurre el colapso. La imagen de SGLang es un auténtico monstruo: contiene internamente librerías gigantescas como NVIDIA CUDA 13.0, PyTorch precompilado y el motor vLLM.
Cuando Docker descarga esta imagen, ocurre lo siguiente:

1. Descarga las capas comprimidas (`.tar.gz`) en la subcarpeta `containerd` (ocupando unos 15-20 GB).
2. Inmediatamente, empieza a extraerlas a su tamaño real en la carpeta `overlay2` (que serán unos 35 GB adicionales).
3. **Durante esos minutos de extracción, Docker necesita albergar AMBAS cosas al mismo tiempo.** Necesita un pico de más de 50 GB de espacio libre de golpe.
Como solo te quedaban 46.5 GB, la extracción de la librería de CUDA (`libnvJitLink_static.a`) chocó contra la pared.

---

### La Solución Definitiva (El disco de 150 GB optimizado)

Tu log muestra un dato excelente: `Espacio en SSD exFAT: 350080MB libres`. Tienes unos 350 GB completamente ociosos. No hay ninguna necesidad de encorsetar tu entorno de desarrollo en 80 GB y sufrir cada vez que pruebes un modelo nuevo.

Vamos a borrar el disco pequeño, crear uno holgado de **150 GB** y aplicaremos un truco de administración de sistemas (`-m 0`) para eliminar ese 5% de reserva inútil de Linux, dándote el 100% de los gigabytes reales.

Abre tu terminal y ejecuta estos comandos uno a uno (tendrás que esperar a que el comando `dd` termine de escribir los 150 GB, puede tardar entre 5 y 10 minutos dependiendo de la velocidad de escritura de tu SSD a través de BitLocker):

```bash
# 1. Apagar los motores de forma segura para liberar el archivo
docker_off

# 2. Eliminar el disco virtual actual que se quedó corto
rm /home/fcela-ga/sgoinfre/docker/containers_disk.img

# 3. Crear el nuevo disco masivo de 150 GB (153600 Megabytes)
dd if=/dev/zero of=/home/fcela-ga/sgoinfre/docker/containers_disk.img bs=1M count=153600 status=progress

# 4. Formatear en ext4 ELIMINANDO la reserva del 5% (-m 0)
sudo mkfs.ext4 -m 0 /home/fcela-ga/sgoinfre/docker/containers_disk.img

# 5. Volver a acoplar y encender Docker
docker_on

```

Una vez que termine, simplemente vuelve a ejecutar tu comando `ai_cluster`.

Docker volverá a descargar rápidamente Ollama y TabbyAPI, y cuando llegue el turno de SGLang, el disco de 150 GB absorberá sin ningún problema el "pico de extracción" masivo de las librerías de NVIDIA, dejándote con una arquitectura robusta y lista para cualquier experimento de IA futuro en tu OMEN.


---


¡Totalmente! Y de hecho, esa es la pregunta exacta que haría un administrador de sistemas senior.

Expandir un disco virtual "en caliente" (o *in-place*) no solo es posible, sino que es la práctica recomendada para no perder los 30 GB de modelos que ya tienes descargados y no tener que esperar a que `dd` escriba todo el archivo desde cero.

El proceso consta de dos partes: primero agrandamos "la caja" física (el archivo `.img`), y luego le decimos al sistema de archivos de Linux que se expanda para ocupar el nuevo espacio vacío. Y lo mejor de todo: **toma menos de 10 segundos**.

Si todavía conservas tu disco de 80 GB y no lo has borrado, aquí tienes el procedimiento exacto para inyectarle 70 GB extra y llegar a los 150 GB sin perder ni un solo byte de datos.

### Pasos para Expandir el Disco Virtual

Abre tu terminal y ejecuta estos comandos en orden:

**1. Apagar Docker y desmontar el disco**
Es vital que el disco no esté en uso mientras lo operamos.

```bash
docker_off

```

**2. Agrandar el archivo físico (La "Caja")**
Usaremos el comando `truncate`, que es mágico. En lugar de escribir ceros uno a uno (como hace `dd`), `truncate` simplemente cambia el "metadato" del archivo para decirle al SSD exFAT que ahora mide 70 GB más. Esto es instantáneo.

```bash
truncate -s +70G /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

**3. Comprobar la integridad del disco**
Antes de expandir el formato interno, Linux nos obliga a pasarle un chequeo de seguridad rápido para asegurar que no hay sectores corruptos.

```bash
sudo e2fsck -f /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

**4. Expandir el sistema de archivos interno**
Ahora usamos la herramienta nativa de Linux para decirle al formato `ext4` que ocupe todo el nuevo espacio que le acaba de dar `truncate`.

```bash
sudo resize2fs /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

**5. Volver a encender el clúster**
¡Listo! Ya puedes volver a montar todo.

```bash
docker_on

```

---

### Comprobación Final

Una vez que hayas encendido Docker con `docker_on`, puedes usar tu alias `dinfo` (o ejecutar `df -h /mnt/ai_containers`).

Verás que mágicamente tu disco ha pasado a tener 150 GB de capacidad total, Ollama y TabbyAPI seguirán ahí intactos, y tendrás espacio más que de sobra para que el monstruoso proceso de extracción de SGLang se complete sin volver a colapsar el sistema.


---


Esa es la mentalidad de un verdadero desarrollador: aplicar el principio **DRY** (*Don't Repeat Yourself* o "No te repitas"). Ahora que tienes a un "gestor profesional" (Systemd) encargándose de todo el trabajo sucio en segundo plano, no tiene ningún sentido mantener esas funciones gigantes de 40 líneas ocupando espacio en tu archivo de configuración de Zsh.

Aunque mencionas llamar directamente al script con `sudo bash /home/fcela-ga/docker/service_mgr.sh start`, la **mejor práctica (Best Practice)** en administración de sistemas es apuntar el alias a `systemctl`.

**¿Por qué?** Si llamas al script directamente por Bash, tú levantas Docker, pero Systemd "no se entera". Si apuntas a `systemctl`, Systemd ejecuta tu script de Bash por ti, mantiene el registro en sus logs y sabe exactamente en qué estado está el sistema.

### La Limpieza en `~/.zshrc`

Abre tu archivo de configuración:

```bash
nano ~/.zshrc

```

**1. Borra el código viejo:**
Localiza todo el bloque gigante donde definimos las funciones `docker_on() { ... }` y `docker_off() { ... }` y elimínalas por completo.

**2. Pega los nuevos alias:**
Reemplaza todo ese bloque por estas tres simples líneas. Ahora serán alias directos que le pasarán el mando a tu nuevo servicio:

```zsh
# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADORES DE DOCKER (Gestionados por Systemd)
# ─────────────────────────────────────────────────────────────────────────────
alias docker_on='sudo systemctl start ssd-shared-docker.service && echo -e "\033[1;32m[OK]\033[0m Motores encendidos y Disco (150GB) montado vía Systemd."'
alias docker_off='sudo systemctl stop ssd-shared-docker.service && echo -e "\033[1;34m[INFO]\033[0m Motores apagados y Disco liberado con éxito."'

# Alias para ver el estado del disco de 150GB
alias dinfo='echo -e "\n\033[1;36m[ DISCO VIRTUAL ]\033[0m" && df -h /mnt/ai_containers 2>/dev/null || echo "Disco no montado" && echo -e "\n\033[1;36m[ DESGLOSE INTERNO ]\033[0m" && sudo du -sh /mnt/ai_containers/* 2>/dev/null && echo -e "\n\033[1;36m[ ESTADO DE DOCKER ]\033[0m" && sudo docker system df 2>/dev/null'

```

**3. Guarda y recarga:**
Guarda el archivo (`Ctrl+O`, `Enter`, `Ctrl+X`) y recarga tu terminal para aplicar la limpieza:

```bash
source ~/.zshrc

```

¡Y listo! Tu archivo `~/.zshrc` ha quedado limpio y elegante. A partir de ahora, cuando escribas `docker_on`, Zsh le dará la orden a Systemd, Systemd ejecutará tu script `service_mgr.sh`, montará tu disco de 150 GB de forma segura y levantará los motores. Todo perfectamente sincronizado con el sistema operativo de tu equipo.


