Para explorar los servicios en tu sistema Ubuntu, la herramienta maestra es `systemctl`. Dependiendo de si quieres ver los que están corriendo ahora mismo, los que arrancan automáticamente, o los archivos físicos que tú mismo has programado, tienes varias formas de filtrarlos.

Aquí tienes los comandos más precisos para listar tus servicios:

### 1. Ver los servicios personalizados (Tus creaciones)

Si quieres ver específicamente los servicios que **tú has creado** a mano (como `ssd-shared-docker.service`), la forma más rápida es mirar directamente en la carpeta donde Linux guarda las configuraciones manuales de administrador:

```bash
ls -lh /etc/systemd/system/*.service

```

*Esto te devolverá una lista limpia de los archivos `.service` que has añadido al sistema, sin mezclarlo con los cientos de servicios nativos de Ubuntu.*

### 2. Ver el estado de "Piloto Automático" (Enabled / Disabled)

Si quieres comprobar qué servicios están configurados para arrancar solos al encender el ordenador y cuáles están bloqueados, utiliza este comando:

```bash
systemctl list-unit-files --type=service

```

Como la lista puede ser inmensa, puedes usar las flechas del teclado para navegar y pulsar la tecla `q` para salir.
Si quieres buscar uno en concreto para ver cómo quedó, puedes filtrarlo con `grep`. Por ejemplo:

```bash
systemctl list-unit-files --type=service | grep -E "docker|ollama"

```

*Esto te mostrará en una sola línea si tu gestor de Docker está `enabled` y si la versión nativa de Ollama quedó correctamente `disabled`.*

### 3. Ver los servicios que están corriendo AHORA MISMO

Para auditar qué está consumiendo recursos o ejecutándose en este preciso instante en segundo plano:

```bash
systemctl list-units --type=service --state=active

```

*Esto te mostrará una tabla con los servicios activos, indicando si están cargados correctamente (`loaded`) y funcionando (`running`).*

### 4. Ver los servicios que han fallado

Como administrador, este es el comando de diagnóstico rápido más útil. Te muestra si algún servicio intentó arrancar pero "crasheó" por algún error en su código o configuración:

```bash
systemctl --failed --type=service

```

*Si te devuelve `0 loaded units listed`, significa que tu sistema está perfectamente sano y ningún servicio ha colapsado.*


