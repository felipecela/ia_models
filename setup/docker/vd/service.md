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


---


Es un acto de gran prudencia por tu parte haber detenido el proceso al ver ese error. En la administración de sistemas, cuando un directorio dice `Device or resource busy` (Dispositivo o recurso ocupado), significa que el kernel de Linux tiene bloqueado ese directorio porque todavía hay un "puente" activo cruzando por él.

**¿Por qué ha pasado esto?**
Hay dos escenarios muy probables por los que esa carpeta sigue ocupada a pesar de haber detenido el servicio:

1. **El orden de las acciones:** Si modificaste el archivo `service_mgr.sh` cambiando la variable a `MNT_DIR="/mnt/docker_containers"` **antes** de ejecutar el comando `systemctl stop`, el script de apagado leyó la nueva ruta e intentó desmontar la carpeta nueva (que estaba vacía), dejando la vieja completamente montada.
2. **Zombie Mounts:** Con los reseteos "duros" (`rm -rf`) que tuvimos que hacerle a Docker en los pasos anteriores para limpiar su caché, es posible que los puntos de montaje de bajo nivel se hayan quedado huérfanos y no hayan respondido a la señal de apagado del servicio.

### El Procedimiento de Limpieza y Aseguramiento

Vamos a desmontar manualmente los tres puentes físicos que conectan con esa carpeta para liberarla. Ejecuta estos comandos uno a uno en tu terminal:

**1. Liberar los enlaces hacia el sistema:**
Desmontamos las rutas donde Docker interactúa. (Añadimos `|| true` para que si ya están desmontados, el comando no lance un error rojo y simplemente continúe).

```bash
sudo umount /var/lib/docker 2>/dev/null || true
sudo umount /var/lib/containerd 2>/dev/null || true

```

**2. Liberar el disco virtual maestro:**
Ahora le decimos a Linux que desconecte el archivo de 150 GB `.img` de la carpeta antigua.

```bash
sudo umount /mnt/ai_containers

```

**3. Eliminar la carpeta (Ahora sí funcionará):**
Al no haber ningún disco ni enlace bloqueando la ruta, el sistema te permitirá borrarla sin rechistar.

```bash
sudo rmdir /mnt/ai_containers

```

### El Lanzamiento Final

Una vez que la carpeta antigua haya desaparecido sin darte errores, significa que el entorno está 100% limpio y liberado de la configuración anterior.

Ya puedes levantar tu servicio con total seguridad:

```bash
sudo systemctl start ssd-shared-docker.service

```

A partir de este punto, tu disco virtual quedará montado de forma permanente y genérica en `/mnt/docker_containers`, y ya podrás volver a lanzar `ai_cluster` o cualquier otro proyecto de contenedores que necesites.


---


Este es un mensaje de protección estándar de Systemd. Como es un gestor que funciona en segundo plano, cuando un script falla o decide abortar (por ejemplo, si se activó nuestra línea de `exit 1` por seguridad), no te lanza el texto del error directamente a la cara, sino que lo guarda en su bitácora o diario interno.

Lo más probable es que, tras los reseteos manuales que hicimos o al editar el script, haya quedado algún "dispositivo loop" (el puente interno de Linux para leer archivos `.img`) enganchado, o que haya un pequeño error de sintaxis tipográfico en la línea que modificaste.

Para no jugar a las adivinanzas, vamos a pedirle a Systemd que nos muestre exactamente qué imprimió tu script justo antes de fallar.

Ejecuta estos dos comandos en tu terminal:

```bash
sudo systemctl status ssd-shared-docker.service

```

```bash
sudo journalctl -u ssd-shared-docker.service -n 20 --no-pager

```

¿Podrías compartirme la salida que te devuelven esos comandos para que podamos identificar la causa exacta y aplicar la solución?


---


¡Perfecto! Traer los logs ha sido la decisión correcta, porque nos han dado el diagnóstico exacto de forma inmediata y sin margen de error.

Fíjate en esta línea específica de tu `journalctl`:
`Failed at step EXEC spawning /home/fcela-ga/docker/service_mgr.sh: Permission denied`

Ese error (`status=203/EXEC`) significa que Systemd sabe dónde está tu script, pero el sistema operativo le ha negado el permiso para **ejecutarlo**.

**¿Por qué ha pasado esto justo ahora si antes funcionaba?**
Cuando abriste el archivo `service_mgr.sh` para modificar la variable de la ruta, es muy probable que tu editor de texto haya guardado los cambios sobrescribiendo el archivo, y en ese proceso, **el archivo perdió su "bandera" de ejecución (`+x`)**. Linux por defecto guarda los archivos de texto solo con permisos de lectura y escritura por seguridad.

### La Solución (Un solo paso)

Para solucionarlo, solo tenemos que devolverle el permiso de ejecución a tu script maestro. Ejecuta este comando en tu terminal:

```bash
chmod +x /home/fcela-ga/docker/service_mgr.sh

```

Una vez devueltos los permisos, el servicio ya podrá lanzar el script sin que Linux lo bloquee. Vuelve a encenderlo con tu comando habitual:

```bash
sudo systemctl start ssd-shared-docker.service

```

Para comprobar que esta vez ha arrancado con éxito y que la nueva carpeta `/mnt/docker_containers` se ha montado correctamente, puedes revisar el estado y verás el semáforo en verde:

```bash
sudo systemctl status ssd-shared-docker.service

```



