#!/bin/bash

DISK_IMG="/home/fcela-ga/sgoinfre/docker/containers_disk.img"
MNT_DIR="/mnt/docker_containers"

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
        # PROTECCIÓN RESTAURADA: Si falla el montaje, abortamos para proteger Ubuntu.
        if ! mount -o loop "$DISK_IMG" "$MNT_DIR"; then
            echo "[ERROR] Falló el montaje del disco virtual. Abortando arranque de Docker."
            exit 1
        fi
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
    
    # 0. Detener el clúster de IA ordenadamente ANTES de tocar Docker
    echo "[DOCKER-AUTO] Apagando el clúster OMEN de forma segura..."
    # Buscamos el comando en el PATH, o si es un alias, ejecutamos el script directamente
    if command -v ai_cluster &>/dev/null; then
        ai_cluster --stop
    elif [ -f "$HOME/ai_cluster/Autoboot_Cluster_V36.sh" ]; then
        bash "$HOME/ai_cluster/Autoboot_Cluster_V36.sh" --stop
    else
        echo "[WARN] Comando 'ai_cluster' no encontrado. Saltando apagado específico de IA."
    fi
    
    # Damos un pequeño respiro para asegurar que procesos de Python (Router) mueran
    sleep 3

    # 1. Detener contenedores suavemente (Equivalente a tu dstop)
    if command -v docker &>/dev/null; then
        RUNNING=$(docker ps -q)
        if [ -n "$RUNNING" ]; then
            echo "[DOCKER-AUTO] Deteniendo contenedores activos residuales..."
            docker stop $RUNNING
        fi
    fi

    # 2. Apagar motores
    echo "[DOCKER-AUTO] Apagando servicios systemd de Docker..."
    systemctl stop docker
    systemctl stop containerd
    systemctl stop docker.socket 2>/dev/null || true

    # 3. Desmontar unidad de forma segura
    echo "[DOCKER-AUTO] Desmontando volumen virtual..."
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
