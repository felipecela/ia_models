#!/bin/bash
# ===== Archivo: Motor-Ollama.sh =====
# Script de control para arrancar y verificar el motor pesado (Híbrido VRAM+RAM)

echo "Asegurando el demonio de Ollama..."
sudo systemctl start ollama

echo "Estado actual del servicio de inferencia de Ollama:"
sudo systemctl status ollama --no-pager

echo "Modelos híbridos listos para usar en memoria compartida:"
ollama list