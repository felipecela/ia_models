# Detener el motor de Docker para poder operar

sudo systemctl stop docker
sudo systemctl stop containerd

sudo systemctl disable docker
sudo systemctl disable docker.socket

sudo umount /var/lib/docker 2>/dev/null


sudo rm -rf /var/lib/docker/*

sudo rm -rf /var/lib/containerd/*

