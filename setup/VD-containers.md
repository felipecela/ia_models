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
