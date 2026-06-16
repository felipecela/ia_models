Reducir un disco virtual es una operación fantástica para recuperar esos valiosos ~50 GB de espacio físico en tu disco real, y dejarlo en 100 GB es el punto de equilibrio perfecto dado que actualmente usas 73 GB.

Sin embargo, **esta es una operación de cirugía mayor**. Si simplemente cortamos el archivo `.img` por la fuerza, corromperemos el sistema de archivos de Linux que vive en su interior.

Para hacerlo de forma 100% segura, utilizaremos la técnica del **"Encogimiento en Dos Fases"**: primero le diremos al sistema de archivos interno que se encoja a 95 GB (para dejar un margen de seguridad temporal), luego cortaremos el archivo físico a 100 GB, y finalmente le diremos al sistema de archivos interno que se vuelva a expandir para ocupar esos 5 GB sobrantes.

Sigue estos pasos exactamente en este orden:

### Paso 1: Apagar y verificar la desconexión

Primero debemos asegurarnos de que Docker está apagado y el disco está completamente liberado.

```bash
docker_off

```

Para estar 100% seguros de que el sistema operativo ya no lo está usando, ejecuta este comando:

```bash
mount | grep docker_containers

```

*(Si no te devuelve nada, el disco está liberado y podemos proceder a operar).*

### Paso 2: Revisión de integridad

Linux no permite cambiar el tamaño de un sistema de archivos sin antes revisarlo en busca de errores. Ejecuta el escáner (esto tomará unos segundos):

```bash
sudo e2fsck -f /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

### Paso 3: Encoger el sistema de archivos (Margen seguro de 95G)

Vamos a comprimir los datos internos para que no haya absolutamente nada escrito más allá del gigabyte 95. Como tienes 73 GB usados, hay espacio de sobra para hacer esto:

```bash
sudo resize2fs /home/fcela-ga/sgoinfre/docker/containers_disk.img 95G

```

### Paso 4: Cortar el archivo físico (A 100G)

Ahora que los datos están agrupados al principio del archivo, podemos "cortar" el sobrante del archivo `.img`. Esto es lo que físicamente te devolverá esos ~48 GB de espacio a tu disco duro real:

```bash
sudo truncate -s 100G /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

### Paso 5: Expandir para un ajuste perfecto

Como cortamos el archivo a 100 GB pero el sistema interno cree que tiene 95 GB, vamos a decirle que aproveche todo el espacio disponible hasta los límites exactos del nuevo archivo, para no desperdiciar ni un solo megabyte:

```bash
sudo resize2fs /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

*(Al ejecutarlo sin ponerle un número al final, `resize2fs` detecta automáticamente que el archivo mide 100 GB y se expande para encajar como un guante).*

### Paso 6: Volver a arrancar

La operación ha terminado. Ya puedes levantar todo tu entorno de nuevo:

```bash
docker_on

```

Si ahora ejecutas tu alias **`dinfo`**, verás que en la sección de `[ DISCO VIRTUAL ]` el "Tamaño" total habrá bajado de 148G a 100G (o 98G/99G, dependiendo de cómo cuente Linux los bloques), manteniendo todos tus contenedores, volúmenes e imágenes completamente intactos y habiendo recuperado el espacio vital en tu máquina física.


---


¡**Escribe `n` y pulsa Enter inmediatamente!** Has tenido un instinto excelente al detenerte. Si le dices que sí a esa advertencia, Linux destrozará el índice del archivo y perderás todos los datos del clúster.

Lo que está ocurriendo es un "montaje fantasma". Aunque tu comando `docker_off` desmontó con éxito la carpeta `/mnt/docker_containers` (por eso el `grep` salió vacío), Linux todavía mantiene abierto el "puente invisible" (el dispositivo `/dev/loop21` que vimos en tu comando `dinfo` anterior) o bien se han quedado atascados los enlaces hacia las carpetas de Docker.

Vamos a soltar esos anclajes a la fuerza para que el archivo quede 100% liberado y podamos operarlo. Ejecuta estos comandos uno por uno en tu terminal:

### 1. Forzar el desmontaje de los enlaces internos

```bash
sudo umount /var/lib/docker 2>/dev/null || true
sudo umount /var/lib/containerd 2>/dev/null || true

```

### 2. Desconectar el dispositivo Loop (El puente invisible)

Este comando buscará qué dispositivo `/dev/loop` tiene secuestrado a tu archivo y lo desconectará de raíz:

```bash
for loop in $(sudo losetup -j /home/fcela-ga/sgoinfre/docker/containers_disk.img | cut -d: -f1); do sudo losetup -d "$loop" || true; done

```

### 3. Limpiar cualquier dispositivo loop residual

Para estar absolutamente seguros de que el kernel de Linux ha soltado el archivo:

```bash
sudo losetup -D

```

---

Una vez ejecutados estos comandos, el archivo `.img` volverá a ser un archivo de texto inerte en tu disco duro.

Ya puedes volver a lanzar el escáner de integridad. Esta vez debería ejecutarse directamente sin mostrarte la advertencia roja:

```bash
sudo e2fsck -f /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

En cuanto termine de escanear (verás que dice "paso 1, paso 2, etc." y finaliza sin errores), puedes continuar con normalidad con los comandos de encogimiento (`resize2fs 95G`, `truncate 100G` y `resize2fs`).


---


¡Perfecto! Actuaste rápido al decir "no" a la advertencia y los comandos de liberación limpiaron los "montajes fantasma" a la perfección.

El resultado de tu escáner (`e2fsck`) es impecable: tu sistema de archivos interno está 100% sano, sin errores y listo para la cirugía.

Ahora sí, podemos proceder a recuperar esos casi 50 GB de espacio libre en tu disco real. Ejecuta estos tres comandos uno detrás de otro:

### 1. Comprimir internamente (A 95G)

Le decimos a Linux que agrupe todos tus datos y deje de usar cualquier espacio más allá de los 95 GB:

```bash
sudo resize2fs /home/fcela-ga/sgoinfre/docker/containers_disk.img 95G

```

*(Verás un mensaje diciendo que el sistema de ficheros se ha redimensionado).*

### 2. Recuperar el espacio físico (Cortar a 100G)

Ahora que no hay datos importantes al final del archivo, damos el "tijeretazo" para recuperar el espacio real en tu SSD:

```bash
sudo truncate -s 100G /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

### 3. Ajuste perfecto (Expandir el sobrante)

Como el archivo ahora mide 100 GB pero el interior cree que mide 95 GB, le decimos que se expanda para rellenar exactamente el nuevo contenedor y no desperdiciar esos 5 GB:

```bash
sudo resize2fs /home/fcela-ga/sgoinfre/docker/containers_disk.img

```

*(Al no ponerle un tamaño, detectará automáticamente el tope de 100G).*

### 4. Arrancar y comprobar

La operación ha terminado. Vuelve a encender los motores de Docker:

```bash
docker_on

```

Y lanza tu comando de diagnóstico:

```bash
dinfo

```

¡Listo! Si miras el resultado de `dinfo`, verás que el disco ha pasado de 148G a 100G (o 98-99G utilizables), que sigues teniendo tus 73 GB de datos intactos y que has liberado casi 50 GB de espacio físico en tu máquina para poder seguir trabajando con tus otros proyectos.



