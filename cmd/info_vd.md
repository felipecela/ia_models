Es una práctica excelente. Ahora que tienes todo encapsulado en ese disco virtual de 80 GB, monitorizar su estado te evitará sorpresas.

Tienes tres formas distintas de revisarlo, dependiendo del nivel de detalle que necesites. Aquí tienes los comandos exactos para tu arquitectura actual.

### 1. Nivel Sistema Operativo (El más rápido)

Para ver cuánto espacio total de los 80 GB del disco virtual has consumido y cuánto te queda libre, utiliza el comando de "disk free" (`df`) apuntando a tu carpeta maestra de anclaje:

```bash
df -h /mnt/ai_containers

```

*Esto te devolverá una tabla muy limpia indicando el tamaño total (Size), lo usado (Used), lo disponible (Avail) y el porcentaje de uso (Use%).*

### 2. Nivel Directorios (Para buscar al "culpable")

Si ves que el disco se está llenando y quieres saber si la culpa es de `docker` (las capas instaladas) o de `containerd` (las descargas temporales), puedes usar el comando "disk usage" (`du`) para pesar las carpetas internamente:

```bash
sudo du -sh /mnt/ai_containers/*

```

*El parámetro `-s` suma el total y la `-h` lo pone en formato humano (Gigabytes/Megabytes).*

### 3. Nivel Docker (La visión del motor)

Docker tiene su propio comando nativo para desglosar exactamente en qué está gastando el espacio internamente (Imágenes, Contenedores activos, Volúmenes locales o Caché de construcción). Para usar este comando, **Docker debe estar encendido** (`docker_on`):

```bash
docker system df

```

*Si quieres ver el detalle exhaustivo línea por línea de cada imagen y contenedor, puedes añadirle el parámetro `-v` (verbose): `docker system df -v`.*

---

### 💡 Extra: Un alias para tu panel de control

Ya que te gusta tener el sistema automatizado y limpio en tu `~/.zshrc`, puedes crearte un alias que te muestre los tres datos de golpe de forma elegante. Si quieres, añade esto a tu archivo de configuración:

```zsh
alias dinfo='echo -e "\n\033[1;36m[ DISCO VIRTUAL (80GB) ]\033[0m" && df -h /mnt/ai_containers && echo -e "\n\033[1;36m[ DESGLOSE INTERNO ]\033[0m" && sudo du -sh /mnt/ai_containers/* 2>/dev/null && echo -e "\n\033[1;36m[ ESTADO DE DOCKER ]\033[0m" && docker system df'

```

Al escribir `dinfo` en tu terminal (siempre que Docker esté encendido), tendrás una radiografía perfecta e instantánea de tu SSD virtual.
