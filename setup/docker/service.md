Es una idea brillante y, de hecho, es el paso definitivo para convertir tu ordenador en un servidor de Inteligencia Artificial de grado profesional.

Automatizar este proceso no solo te ahorra escribir comandos cada vez que enciendes el equipo, sino que te garantiza que el sistema operativo gestionará el apagado de los contenedores y el desmontaje del disco de 150 GB de forma impecable en caso de un reinicio inesperado, eliminando el riesgo de corrupción.

Para lograr esto en la arquitectura de Ubuntu, vamos a crear un "Servicio de Sistema" (`systemd`). El proceso requiere 4 pasos y ejecutaremos todo como usuario administrador.

### 1. Evitar la "Carrera de Arranque"

Lo primero y más importante es quitarle a Docker el permiso para arrancar por sí solo. Si Ubuntu arranca Docker *antes* de que nuestra unidad virtual esté montada, Docker volverá a descargar datos en tus 20 GB del disco principal.

Ejecuta esto en tu terminal para desactivar el auto-arranque nativo:

```bash
sudo systemctl disable docker containerd docker.socket

```

### 2. Crear el Script Maestro (`auto_docker.sh`)

Vamos a crear un archivo que contenga la inteligencia de arranque y apagado, incluyendo un bucle de espera por si el SSD cifrado tarda unos segundos en estar disponible al encender el PC.

Crea y abre el archivo:

```bash
nano /home/fcela-ga/ai_cluster/auto_docker.sh

```

Pega el siguiente código exacto (fíjate que ya no usamos `sudo` internamente, porque el servicio lo ejecutará directamente como administrador):

```bash
#!/bin/bash

DISK_IMG="/home/fcela-ga/sgoinfre/docker/containers_disk.img"
MNT_DIR="/mnt/ai_containers"

start_docker() {
    echo "[DOCKER-AUTO] Esperando a que el disco virtual esté disponible..."
    # Esperar hasta 60s a que la unidad se monte (útil para discos cifrados)
    WAIT=0
    while [ ! -f "$DISK_IMG" ]; do
        sleep 2
        WAIT=$((WAIT + 2))
        if [ $WAIT -ge 60 ]; then
            echo "[ERROR] Timeout de 60s: El archivo containers_disk.img no está accesible."
            exit 1
        fi
    done

    echo "[DOCKER-AUTO] Montando disco de 150 GB..."
    mkdir -p "$MNT_DIR"
    if ! mountpoint -q "$MNT_DIR"; then
        mount -o loop "$DISK_IMG" "$MNT_DIR"
        mkdir -p "$MNT_DIR/docker" "$MNT_DIR/containerd"
        mkdir -p /var/lib/docker /var/lib/containerd
        mount --bind "$MNT_DIR/docker" /var/lib/docker
        mount --bind "$MNT_DIR/containerd" /var/lib/containerd
    fi
    
    echo "[DOCKER-AUTO] Iniciando motores..."
    systemctl start containerd
    systemctl start docker
    echo "[DOCKER-AUTO] Entorno operativo y aislado."
}

stop_docker() {
    echo "[DOCKER-AUTO] Iniciando secuencia de apagado..."
    
    # 1. Detener contenedores suavemente (Equivalente a tu dstop)
    if command -v docker &>/dev/null; then
        RUNNING=$(docker ps -q)
        if [ -n "$RUNNING" ]; then
            echo "[DOCKER-AUTO] Deteniendo contenedores activos..."
            docker stop $RUNNING
        fi
    fi

    # 2. Apagar motores
    systemctl stop docker
    systemctl stop containerd
    systemctl stop docker.socket 2>/dev/null || true

    # 3. Desmontar unidad de forma segura
    if mountpoint -q /var/lib/docker; then umount /var/lib/docker; fi
    if mountpoint -q /var/lib/containerd; then umount /var/lib/containerd; fi
    if mountpoint -q "$MNT_DIR"; then umount "$MNT_DIR"; fi
    
    echo "[DOCKER-AUTO] Disco virtual liberado con éxito."
}

case "$1" in
    start) start_docker ;;
    stop)  stop_docker ;;
    *) echo "Uso: $0 {start|stop}" ;;
esac

```

Guarda el archivo (`Ctrl+O`, `Enter`, `Ctrl+X`) y dale permisos de ejecución:

```bash
chmod +x /home/fcela-ga/ai_cluster/auto_docker.sh

```

### 3. Crear el Servicio de Systemd

Ahora le diremos a Ubuntu que utilice ese script cada vez que se encienda o se apague el ordenador.

Crea el archivo del servicio en la carpeta del sistema:

```bash
sudo nano /etc/systemd/system/omen-ai-docker.service

```

Pega esta configuración:

```ini
[Unit]
Description=OMEN AI Cluster Virtual Disk & Docker Manager
After=network.target local-fs.target
Requires=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/home/fcela-ga/ai_cluster/auto_docker.sh start
ExecStop=/home/fcela-ga/ai_cluster/auto_docker.sh stop
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target

```

*Nota: `TimeoutStopSec=120` le da a Ubuntu un margen de 2 minutos al apagar el PC para asegurarse de que todos tus modelos de IA guarden su memoria caché y se detengan limpiamente.*

Guarda el archivo y ciérralo.

### 4. Activar la Automatización

Finalmente, solo necesitas recargar la lista de servicios de Ubuntu y activar el tuyo de forma permanente:

```bash
sudo systemctl daemon-reload
sudo systemctl enable omen-ai-docker.service

```

### ¿Qué ocurrirá a partir de ahora?

Tu entorno está blindado. Cuando pulses el botón de encendido de tu OMEN, Ubuntu montará silenciosamente el disco virtual y encenderá Docker. Para cuando abras tu terminal, todo estará listo para que lances `ai_cluster`.

Y cuando le des a apagar al sistema, Ubuntu interceptará la señal de apagado, lanzará la función `stop` de tu script (deteniendo tus contenedores y desmontando el archivo de 150 GB) y luego apagará el ordenador con total seguridad. Ya no necesitas preocuparte por ejecutar `docker_off` manualmente a menos que quieras liberar recursos sin apagar el PC.


---


Me parece una decisión arquitectónica brillante. Al sacar el script de la carpeta `ai_cluster` y llevarlo a un entorno genérico como `~/docker/service_mgr.sh`, has convertido lo que era un "parche" para la IA en un servicio de sistema de primer nivel.

Esto tiene todo el sentido del mundo, especialmente considerando que ese SSD exFAT es tu unidad compartida entre Ubuntu y Windows 11. Al hacer que este servicio gestione de forma independiente el montaje del disco virtual, te aseguras de que Docker funcione a la perfección sin importar si ese día vas a levantar el clúster de IA o si vas a trabajar en otros contenedores para tus proyectos en C++.

**¡Pero ojo con un detalle crítico en tu archivo!**
Al copiar o editar el texto, te has comido el corchete de apertura en la primera línea. Tienes escrito `Unit]` y Linux es implacable con la sintaxis de Systemd; si lo dejas así, el servicio fallará al intentar leerlo.

Asegúrate de corregirlo para que quede exactamente así:

```ini
[Unit]
Description=OMEN SSD Shared - Virtual Disk & Docker Manager
After=network.target local-fs.target
Requires=local-fs.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/home/fcela-ga/docker/service_mgr.sh start
ExecStop=/home/fcela-ga/docker/service_mgr.sh stop
TimeoutStopSec=120

[Install]
WantedBy=multi-user.target

```

Una vez que corrijas ese `[Unit]`, recuerda que al haberle cambiado el nombre al servicio, tendrás que registrarlo en el sistema con estos dos comandos:

```bash
sudo systemctl daemon-reload
sudo systemctl enable ssd-shared-docker.service

```

Con esta base sólida y aislada gestionando el disco de 150 GB en las sombras de Ubuntu, el orquestador (`Autoboot_Cluster_V21.sh`) ya no tiene que preocuparse por la infraestructura física.

¿Pudiste aplicar la lógica de *Reutilización Inteligente* (`is_container_running`) en el script que comentábamos en el paso anterior? Si logramos que el script deje de matar a ChromaDB en cada arranque y simplemente reutilice el contenedor que ya tiene la base de datos inicializada, es casi seguro que ese molesto timeout de 30 segundos desaparecerá para siempre.


---


Para interactuar con tu nuevo gestor de servicios, tienes dos opciones correctas:

La forma manual (para pruebas):

Bash
sudo bash /home/fcela-ga/docker/service_mgr.sh start
La forma nativa de Linux (La recomendada):

Bash
sudo systemctl start ssd-shared-docker.service
sudo systemctl stop ssd-shared-docker.service

El estado general del servicio (La primera línea de defensa):
sudo systemctl status ssd-shared-docker.service

Inspeccionar los registros del servicio (Logs en tiempo real):
sudo journalctl -u ssd-shared-docker.service -n 50 --no-pager

Verificar los puntos de montaje físicos (La prueba real):
mount | grep -E "ai_containers|var/lib/docker|var/lib/containerd"

Comprobar el espacio libre real de Docker
Para asegurarte al 100% de que el motor de Docker está escribiendo dentro de los 150 GB aislados del SSD y no en tus 20 GB del disco principal de Ubuntu, lánzale una consulta de espacio a la carpeta puente:
df -h /mnt/ai_containers

Verificar que los demonios responden
Por último, comprueba si los servicios de fondo que levantó el script están escuchando peticiones en el sistema:
sudo systemctl is-active docker containerd

