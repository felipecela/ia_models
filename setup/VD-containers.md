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
