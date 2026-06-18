Perfecto. Con todo claro, aquí tienes el conjunto de aliases completo y razonado para tu `.zshrc`:

## Aliases para `.zshrc`

```zsh
# ─── Docker — Gestión de contenedores ────────────────────────────────────────
alias dstop='docker stop $(docker ps -q)'                          # Para todos los running
alias dkill='docker rm -f $(docker ps -aq)'                        # Elimina todos (running + parados)
alias dclean='docker container prune -f'                           # Elimina solo los parados

# ─── Docker — Redes ──────────────────────────────────────────────────────────
alias dnetrm='docker network prune -f'                             # Elimina redes no usadas por ningún contenedor
alias dnetls='docker network ls'                                   # Listar todas las redes

# ─── Docker — Volúmenes ──────────────────────────────────────────────────────
# AVISO: solo elimina volúmenes NO asociados a ningún contenedor (running o parado)
# chromadb_data y ollama_gpu_data están seguros mientras sus contenedores existan
alias dvolrm='docker volume prune -f'                              # Elimina volúmenes huérfanos (anónimos)
alias dvolrm-all='docker volume prune -a -f'                       # Elimina TODOS los no usados (incluye nombrados sin contenedor)
alias dvolls='docker volume ls'                                    # Listar todos los volúmenes

# ─── Docker — Build cache ────────────────────────────────────────────────────
alias dcacherm='docker builder prune -f'                           # Elimina build cache dangling
alias dcacherma='docker builder prune -a -f'                       # Elimina TODO el build cache

# ─── Docker — Purga completa SIN imágenes ────────────────────────────────────
# Equivale a: contenedores parados + redes huérfanas + build cache dangling
# NO toca: imágenes, volúmenes nombrados (chromadb_data, etc.), contenedores running
alias dprune='docker container prune -f && docker network prune -f && docker builder prune -f'

# ─── Docker — Purga agresiva SIN imágenes ────────────────────────────────────
# Añade volúmenes huérfanos anónimos al dprune. Los volúmenes NOMBRADOS (chromadb_data,
# ollama_gpu_data) están protegidos mientras su contenedor exista o haya sido creado.
alias dpruneall='docker container prune -f && docker network prune -f && docker volume prune -f && docker builder prune -a -f'

# ─── Docker — Diagnóstico de espacio ─────────────────────────────────────────
alias ddf='docker system df -v'                                    # Qué ocupa qué
alias dips='docker inspect -f "{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" $(docker ps -q)'  # IPs de containers running
```

***

## Qué protege cada alias

| Alias | Contenedores | Redes | Volúmenes | Build cache | Imágenes |
|---|---|---|---|---|---|
| `dprune` | ✅ elimina parados | ✅ elimina huérfanas | 🔒 intactos | ✅ dangling | 🔒 intactas |
| `dpruneall` | ✅ elimina parados | ✅ elimina huérfanas | ⚠ elimina anónimos | ✅ todo cache | 🔒 intactas |
| `dvolrm` | — | — | ⚠ solo huérfanos | — | 🔒 intactas |
| `dvolrm-all` | — | — | ⚠ todos sin contenedor | — | 🔒 intactas |

## Protección de tus volúmenes nombrados

`chromadb_data` y `ollama_gpu_data` son volúmenes **nombrados**. Tanto `dvolrm` como `dvolrm-all` solo eliminan volúmenes que no tienen ningún contenedor asociado — ni running ni parado. Mientras el contenedor `chromadb` o `ollama-gpu-main` exista en Docker (aunque esté parado), sus volúmenes están seguros. [docs.docker](https://docs.docker.com/engine/manage-resources/pruning/)

El flujo recomendado cuando tengas conflictos como el de hoy es:

```zsh
dstop        # Para todo
dprune       # Limpia contenedores parados + redes huérfanas + build cache
ai_cluster   # Relanza el autoboot
```


# ─────────────────────────────────────────────────────────────────────────────
# CONTROLADORES DE DOCKER (Gestionados por Systemd)
# ─────────────────────────────────────────────────────────────────────────────
alias docker_on='sudo systemctl start ssd-shared-docker.service && echo -e "\033[1;32m[OK]\033[0m Motores encendidos y Disco (100GB) montado vía Systemd."'
alias docker_off='sudo systemctl stop ssd-shared-docker.service && echo -e "\033[1;34m[INFO]\033[0m Motores apagados y Disco liberado con éxito."'

# Alias para ver el estado del disco de 150GB
alias dinfo='echo -e "\n\033[1;36m[ DISCO VIRTUAL ]\033[0m" && df -h /mnt/ai_containers 2>/dev/null || echo "Disco no montado" && echo -e "\n\033[1;36m[ DESGLOSE INTERNO ]\033[0m" && sudo du -sh /mnt/ai_containers/* 2>/dev/null && echo -e "\n\033[1;36m[ ESTADO DE DOCKER ]\033[0m" && sudo docker system df 2>/dev/null'



# En ~/.zshrc — añadir "$@" al final de bash "$LATEST_SCRIPT"
ai_cluster() {
    local LATEST_SCRIPT=$(ls -v "$HOME/ai_cluster"/Autoboot_Cluster_V??.sh 2>/dev/null | tail -n 1)
    if [[ -f "$LATEST_SCRIPT" ]]; then
        echo -e "\033[1;36m[SISTEMA]\033[0m Autodetectada la última versión: $(basename "$LATEST_SCRIPT")"
        bash "$LATEST_SCRIPT" "$@"
    else
        echo -e "\033[0;31m[ERROR]\033[0m No se encontró ningún script Autoboot_Cluster_V??.sh"
    fi
}


---


# ─── Docker — Gestión de contenedores ────────────────────────────────────────
alias dstop='docker stop $(docker ps -q)'                          # Para todos los running
alias dkill='docker rm -f $(docker ps -aq)'                        # Elimina todos (running + parados)
alias dclean='docker container prune -f'                           # Elimina solo los parados

# ─── Docker — Redes ──────────────────────────────────────────────────────────
alias dnetrm='docker network prune -f'                             # Elimina redes no usadas por ningún contenedor
alias dnetls='docker network ls'                                   # Listar todas las redes

# ─── Docker — Volúmenes ──────────────────────────────────────────────────────
# AVISO: solo elimina volúmenes anónimos NO asociados a ningún contenedor
alias dvolrm='docker volume prune -f'                              # Elimina volúmenes huérfanos (anónimos)
alias dvolrm-all='docker volume prune -a -f'                       # Elimina TODOS los no usados (incluye nombrados sin contenedor)
alias dvolls='docker volume ls'                                    # Listar todos los volúmenes

# ─── Docker — Build cache ────────────────────────────────────────────────────
alias dcacherm='docker builder prune -f'                           # Elimina build cache dangling
alias dcacherma='docker builder prune -a -f'                       # Elimina TODO el build cache

# ─── Docker — Purga estándar SIN imágenes ────────────────────────────────────
# Equivale a: contenedores parados + redes huérfanas + build cache dangling
# NO toca: imágenes, volúmenes, contenedores running
alias dprune='docker container prune -f && docker network prune -f && docker builder prune -f'

# ─── Docker — Purga agresiva segura ──────────────────────────────────────────
# Añade volúmenes ANÓNIMOS y TODA la caché de compilación (dcacherma).
# Los volúmenes NOMBRADOS (chromadb_data, etc.) ESTÁN PROTEGIDOS.
alias dpruneall='docker container prune -f && docker network prune -f && docker volume prune -f && docker builder prune -a -f'

# ─── Docker — Purga PROFUNDA ─────────────────────────────────────────────────
# Incluye dvolrm-all: Eliminará contenedores parados, redes, TODA la caché
alias dpruneall-deep='docker network prune -f && docker volume prune -a -f && docker builder prune -a -f'
# ─── Docker — Diagnóstico de espacio ─────────────────────────────────────────
alias ddf='docker system df -v'                                    # Qué ocupa qué
alias dips='docker inspect -f "{{.Name}} {{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" $(docker ps -q)'  # IPs de containers running



