### Usar `pipx` (La que te recomendé antes)

Si recuerdas la "Opción 2" de mi mensaje anterior, instalar vía `pipx` esquiva este problema por completo. `pipx` instala las herramientas en `~/.local/pipx/` (tu directorio home), por lo que el ejecutable `huggingface-cli` se instalará en una partición nativa y podrás llamarlo desde `sgoinfre` sin preocuparte por el formato exFAT.

```zsh
sudo apt install -y pipx
pipx ensurepath
pipx install huggingface_hub

```



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
