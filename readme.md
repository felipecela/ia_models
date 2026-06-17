## SGLang en CPU/RAM: técnicamente posible, pero no con la imagen actual

SGLang **sí tiene modo CPU** mediante el paquete `sglang-cpu` con la variable de entorno `SGLANG_USE_CPU_ENGINE=1`, pero **requiere una imagen Docker completamente diferente** a `lmsysorg/sglang:latest` (que es exclusivamente CUDA). Además, la documentación oficial indica que el soporte CPU real está optimizado para Intel Xeon 4ª gen+ con extensiones AMX, y en AMD/Intel genérico el rendimiento es tan bajo que inferencia en tokens/s es prácticamente inutilizable para un flujo de trabajo real. [leeroopedia](https://leeroopedia.com/index.php/Environment:Sgl_project_Sglang_CPU)

Existe el flag `--cpu-offload-gb N` que descarga N GB de capas a RAM del sistema manteniendo el resto en VRAM, pero hay bugs conocidos con esta combinación en modelos AWQ. No te recomiendo este camino para producción. [github](https://github.com/sgl-project/sglang/issues/6526)

***

## La chuleta que te faltaba — Modelos por motor

Tu cluster tiene **3 capas de inferencia** con propósitos y fortalezas distintas: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)

| Motor | Puerto | Modelo(s) cargados | Tipo inferencia | Mejor para |
|---|---|---|---|---|
| **Ollama GPU** | `:11434` | `deepseek-r1:14b` · `phi4-reasoning:plus` · `phi4-reasoning:14b-q4_K_M` · `qwen2.5:32b` | VRAM GPU | Razonamiento profundo, respuestas largas |
| **TabbAPI ExLlamaV2** | `:5000` | `llama-3.1-8b-exl2` | VRAM GPU (EXL2) | Respuestas rápidas/chat instantáneo, coding |
| **Ollama CPU** | `:11435` | `nomic-embed-text` · `phi4-mini` | RAM CPU | Embeddings, routing, tareas ligeras |
| **SGLang** | `:30000` | `llama-3.1-8b-awq` | VRAM GPU (AWQ) | Throughput alto, batching paralelo |
| **ChromaDB** | `:8001` | — | Vector DB | Búsqueda semántica del vault Obsidian |
| **SearXNG** | `:8888` | — | Web search | Búsquedas en tiempo real |

### Ranking de razonamiento real (de mayor a menor)

1. **`qwen2.5:32b`** — el más potente del cluster, 32B parámetros, ideal para análisis complejos [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)
2. **`phi4-reasoning:plus`** — la versión reforzada de razonamiento de Phi-4, excelente relación calidad/VRAM [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)
3. **`deepseek-r1:14b`** — entrenado específicamente para chain-of-thought, razonamiento matemático y lógico [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)
4. **`phi4-reasoning:14b-q4_K_M`** — misma base que el anterior pero cuantizado, más rápido con algo menos de precisión [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)
5. **`llama-3.1-8b-exl2` / `llama-3.1-8b-awq`** — modelos de 8B, buenos para chat rápido pero no para razonamiento profundo [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)
6. **`phi4-mini`** — modelo pequeño, solo para routing y clasificación de tareas [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)
7. **`nomic-embed-text`** — no genera texto, solo embeddings vectoriales para ChromaDB [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)

### La restricción de VRAM en contexto

El problema de SGLang no es diseño, es una **colisión de recursos en 8GB**: TabbAPI (`llama-3.1-8b-exl2`) ya ocupa ~6.9 GB de VRAM, y SGLang (`llama-3.1-8b-awq`) necesitaría otros ~5.5 GB. El router ya contempla esto y omite SGLang mostrando el aviso correcto. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYEYWYK6ERB&Signature=p0QT%2FFcd%2Baj09twdX2K3LFTakfY%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJGMEQCIA4H0rweEmB8zQNEEwQmfl6u%2BCqswCzZU32M05quTiEBAiBASKHX3gsOGFcq5d6%2FI0wjnkOULiC6Asvj6rHsh88qiirzBAh9EAEaDDY5OTc1MzMwOTcwNSIMMtTWHSGziAT%2FStSZKtAEjqBnrelub2jRXxm%2F1xcsWjMZppuZs0QTYQ2HBMyX09v2Bw5nzH0DGrUjR1W5%2BlWlmDwL69GMdrjfk7Fb2gRHG4dSbZ1WZfugAJCxutL5Tfv1ZI1ceTwjV3LkBtHTcX8FQdpMSCCGmRb3cqZe%2BUih6D3qqOfusIYXsCNPult3Dkf%2FK41uFRzZSl18M8m4Tuf44lPm8TyZ8l1V577rjNp2aWLHBwEIU8L8h55ug1%2BvqjH9cUTYn0uvJRwYVAEE0QynFupw4iRcfC9Pm1CGjeDxxz0zXZANdGnw0XTJTWQuYSbyXeE7536ktD1FkWfBQiKtt6H0beLxYgD8e1%2BWSqUg13fmI2pwfN6wcfMYLmK8SKOWDFD3OUqEMlMPK0eleSas6M2RSVqKO5pmrNLMn1o52jnGLjEAov2ebrGcToP4dLeuQb%2BbFTsH7zIOspLpfhrisBcVh%2FV5OmEHFiaaZgWZmaPHnUBRejJi5Jfv1S2bmwqCtZvHBK9GUzaiBhFjblhxXdBFLpK6DyLBPMQfh6GMkOoaniyGPLy5%2BIU%2B1Z7wuM%2BBjZnwbtt4N%2BKzZE1LYPrD4VIlEoYw0tj7fr39AMy5S5vE6B%2FagQgD5dtADR6K%2BTKpyJF1VmNoaxwVZ27ApKMMLbbWiN6mpop23gT9pOMEoZwSjjr0UiTl7k1v9OefBElTDN20IyrqFrM2A8IRyWmSvrZoSS4l0JK0G4SCX7zQmk7ASwVrNtry%2B0H0OacHL2cvF2ZEFB%2BuD%2FF32Cj2ceMwLi7fn3zXjdY9I%2B3Co0xQMjC%2B28bRBjqZAb36sqlIhnD9EMCZJuHxclZZcQ80aQKtYNYaiIfAeup%2Fs7y4UTEysFFS%2BFEONZu1MUyRlxWpK0%2BCcC91%2BlIYVsxQa29Z%2FFEFM3KWBaOHWfTB3DFcHMTukLrbIHBHrXEWVxUu6afA5wT%2BnrGVU11WuhI%2FrYVDF89vKj%2Fje9qhbqs5uU2%2FX2E56BazeJTWdpyKjTyuLFT9WSzLTw%3D%3D&Expires=1781644177)

La decisión de diseño que tomaste tiene sentido: Ollama GPU con DeepSeek R1 y Phi4-Reasoning son tus motores de razonamiento principal, y TabbAPI cubre el chat rápido. SGLang era útil para batching en producción multi-usuario, pero con un solo usuario su ausencia no es un problema práctico. 


---


Decisiones de diseño muy claras. Ahora tengo todo lo que necesito para responderte con precisión y sin ambigüedad.

***

## Sobre la chuleta en el script: la respuesta corta es no

Tienes toda la razón en plantearlo. El `printf` de la chuleta al final del autoboot no afecta al rendimiento del sistema (es solo texto en stdout, no ejecuta nada), pero **sí alarga la salida** de forma significativa en cada arranque. Como ya tienes el README con esa información, no tiene sentido duplicarlo. La chuleta queda fuera — decisión correcta. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYET2DLZV2C&Signature=WhUDsHcDn17JZ05VAS9kxrlEjCk%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIGA2M%2FpXsKZXzW5Q8NzD9V6TZj2eOX0yg8f3dl%2BRaBNJAiEA%2BZAcamk33qK3PY7T3hjjEdGrh0txAeLSfwYfbR4XKREq8wQIfhABGgw2OTk3NTMzMDk3MDUiDBHvUNY%2FAezzvIS1pSrQBLxL2uwy7bnoXQRYdt%2Fzj%2FHJCNwZl4n8iy8%2FbCTBullz5wGvH98Ue6KM9JJ0wn%2BdPo8T4BlVVfAxoX3tvcYKxAMrGYYu%2BCvI1IQlUfdA6CvJ1z%2F1SKCzwiC2AP0WNwh8a%2BCGnnzAMy0qTaSy2IR6l817KoBsGQcudn3Bl9LbP9MabGieTeh8s0XZJzDYWNFC8%2B6LMKcb1zfJZYFq3%2BrYHrk2djES3cGLyuDz75yVkUjrwLADiql46%2BBB9UpKqG7JxZgWHf9u2%2BCeiDL94mToh5V%2BTpzWHZnzKQ6XvFhCXkW%2B0zce6eqA7%2FT20j3x%2FvfcBEC0rrLu3RmFtTTuusdupL6YaBiIsloZQk6TlLDowyc%2FbW7o5bdDQfF1zx0V%2BW9jl83QxFOIEwVjyXx%2Bulog0%2F5CfCsjbl9ilRpuz91FAiJZcZH%2Btu4gfe0%2BoJhaVPd7CFr7HMVX56Y4PxllYavY7tSKjnLjU%2FuXIhn5HUC2PvZQnWAaz1XF2IQV5caeqFGtr7sb9drG6QPzpmSDv11VT84VRz6Mu%2BGSFJXIvs4SqhCijpXPJeMZTDHIY9%2Beq9FrdDhD0ia1%2FaHzM4G%2BGTEgnoR0ZRKaz%2Bc0kw20LPltoVjGruoXq6MkWrlbIvLXK4nF1HuTkuedgmQtRH15fhq1d%2BtkgY8P6U8dMQMcvnn8dZIn%2BdzdHv86T2u%2FH%2FO71qGMktUVRS08jsgwH09VfOuULD76eDhvaw2L1%2FQk14ypiR4MPFDVp0lg0NsLbm%2FFJMdj5ckTPkTO3Lnjods2vuPe4Vow%2BO%2FG0QY6mAFZ4vPeq99E5llZI%2BBYgRAEbbLGWshbkOQM7pdzJ4sKcwtNRJvxVin69u8qJ6qqeDrKL49KmiB%2FEAHc%2B%2F2e1ZUfbQPfXhhb5Q8B54%2BcxUIfY0yymfqvpw55V7gIREQ3dY%2FaswxtYlpuirnewheC96dNeYqm9TVutl0jx4lEC%2FqMJyJtna4dKpFroYGdjhIwTQCGhnTyrIEQcw%3D%3D&Expires=1781646795)

***

## El flag `--sglang`: diseño exacto

Lo que propones encaja perfectamente con la arquitectura del script. Así es como funcionaría:

**Comportamiento por defecto (`ai_cluster`):**
- TabbAPI EXL2 activo → `llama-3.1-8b-exl2` en VRAM
- SGLang omitido (VRAM insuficiente, aviso informativo)

**Comportamiento con `ai_cluster --sglang`:**
1. Si TabbAPI está corriendo → `docker stop exllamav2-api` (libera ~6.9 GB VRAM)
2. Lanza SGLang con `llama-3.1-8b-awq`
3. El resumen final refleja el modo activo

El flag se gestiona al inicio del script junto al resto de argumentos (`--stop`, `--status`, `--reindex`, etc.), y condiciona los bloques 3/7 y 4/7. En el resumen final muestra la columna "Modo VRAM" para que siempre quede claro qué motor GPU está activo. [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/5ffc0d51-8088-40f4-9083-f08ac4009e81/Autoboot_Cluster_V21.sh?AWSAccessKeyId=ASIA2F3EMEYET2DLZV2C&Signature=WhUDsHcDn17JZ05VAS9kxrlEjCk%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIGA2M%2FpXsKZXzW5Q8NzD9V6TZj2eOX0yg8f3dl%2BRaBNJAiEA%2BZAcamk33qK3PY7T3hjjEdGrh0txAeLSfwYfbR4XKREq8wQIfhABGgw2OTk3NTMzMDk3MDUiDBHvUNY%2FAezzvIS1pSrQBLxL2uwy7bnoXQRYdt%2Fzj%2FHJCNwZl4n8iy8%2FbCTBullz5wGvH98Ue6KM9JJ0wn%2BdPo8T4BlVVfAxoX3tvcYKxAMrGYYu%2BCvI1IQlUfdA6CvJ1z%2F1SKCzwiC2AP0WNwh8a%2BCGnnzAMy0qTaSy2IR6l817KoBsGQcudn3Bl9LbP9MabGieTeh8s0XZJzDYWNFC8%2B6LMKcb1zfJZYFq3%2BrYHrk2djES3cGLyuDz75yVkUjrwLADiql46%2BBB9UpKqG7JxZgWHf9u2%2BCeiDL94mToh5V%2BTpzWHZnzKQ6XvFhCXkW%2B0zce6eqA7%2FT20j3x%2FvfcBEC0rrLu3RmFtTTuusdupL6YaBiIsloZQk6TlLDowyc%2FbW7o5bdDQfF1zx0V%2BW9jl83QxFOIEwVjyXx%2Bulog0%2F5CfCsjbl9ilRpuz91FAiJZcZH%2Btu4gfe0%2BoJhaVPd7CFr7HMVX56Y4PxllYavY7tSKjnLjU%2FuXIhn5HUC2PvZQnWAaz1XF2IQV5caeqFGtr7sb9drG6QPzpmSDv11VT84VRz6Mu%2BGSFJXIvs4SqhCijpXPJeMZTDHIY9%2Beq9FrdDhD0ia1%2FaHzM4G%2BGTEgnoR0ZRKaz%2Bc0kw20LPltoVjGruoXq6MkWrlbIvLXK4nF1HuTkuedgmQtRH15fhq1d%2BtkgY8P6U8dMQMcvnn8dZIn%2BdzdHv86T2u%2FH%2FO71qGMktUVRS08jsgwH09VfOuULD76eDhvaw2L1%2FQk14ypiR4MPFDVp0lg0NsLbm%2FFJMdj5ckTPkTO3Lnjods2vuPe4Vow%2BO%2FG0QY6mAFZ4vPeq99E5llZI%2BBYgRAEbbLGWshbkOQM7pdzJ4sKcwtNRJvxVin69u8qJ6qqeDrKL49KmiB%2FEAHc%2B%2F2e1ZUfbQPfXhhb5Q8B54%2BcxUIfY0yymfqvpw55V7gIREQ3dY%2FaswxtYlpuirnewheC96dNeYqm9TVutl0jx4lEC%2FqMJyJtna4dKpFroYGdjhIwTQCGhnTyrIEQcw%3D%3D&Expires=1781646795)

***

## Los dos modos en contexto de rutas del router

Revisando el router V14, los niveles que dependen de cada motor son: [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/7a2f9443-1ef1-47c4-8c84-9c05ddd1fffb/orchestrator_router_V14.py?AWSAccessKeyId=ASIA2F3EMEYET2DLZV2C&Signature=cVUltQeX%2Bg5M0pCdxTC%2FzxtNuEs%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIGA2M%2FpXsKZXzW5Q8NzD9V6TZj2eOX0yg8f3dl%2BRaBNJAiEA%2BZAcamk33qK3PY7T3hjjEdGrh0txAeLSfwYfbR4XKREq8wQIfhABGgw2OTk3NTMzMDk3MDUiDBHvUNY%2FAezzvIS1pSrQBLxL2uwy7bnoXQRYdt%2Fzj%2FHJCNwZl4n8iy8%2FbCTBullz5wGvH98Ue6KM9JJ0wn%2BdPo8T4BlVVfAxoX3tvcYKxAMrGYYu%2BCvI1IQlUfdA6CvJ1z%2F1SKCzwiC2AP0WNwh8a%2BCGnnzAMy0qTaSy2IR6l817KoBsGQcudn3Bl9LbP9MabGieTeh8s0XZJzDYWNFC8%2B6LMKcb1zfJZYFq3%2BrYHrk2djES3cGLyuDz75yVkUjrwLADiql46%2BBB9UpKqG7JxZgWHf9u2%2BCeiDL94mToh5V%2BTpzWHZnzKQ6XvFhCXkW%2B0zce6eqA7%2FT20j3x%2FvfcBEC0rrLu3RmFtTTuusdupL6YaBiIsloZQk6TlLDowyc%2FbW7o5bdDQfF1zx0V%2BW9jl83QxFOIEwVjyXx%2Bulog0%2F5CfCsjbl9ilRpuz91FAiJZcZH%2Btu4gfe0%2BoJhaVPd7CFr7HMVX56Y4PxllYavY7tSKjnLjU%2FuXIhn5HUC2PvZQnWAaz1XF2IQV5caeqFGtr7sb9drG6QPzpmSDv11VT84VRz6Mu%2BGSFJXIvs4SqhCijpXPJeMZTDHIY9%2Beq9FrdDhD0ia1%2FaHzM4G%2BGTEgnoR0ZRKaz%2Bc0kw20LPltoVjGruoXq6MkWrlbIvLXK4nF1HuTkuedgmQtRH15fhq1d%2BtkgY8P6U8dMQMcvnn8dZIn%2BdzdHv86T2u%2FH%2FO71qGMktUVRS08jsgwH09VfOuULD76eDhvaw2L1%2FQk14ypiR4MPFDVp0lg0NsLbm%2FFJMdj5ckTPkTO3Lnjods2vuPe4Vow%2BO%2FG0QY6mAFZ4vPeq99E5llZI%2BBYgRAEbbLGWshbkOQM7pdzJ4sKcwtNRJvxVin69u8qJ6qqeDrKL49KmiB%2FEAHc%2B%2F2e1ZUfbQPfXhhb5Q8B54%2BcxUIfY0yymfqvpw55V7gIREQ3dY%2FaswxtYlpuirnewheC96dNeYqm9TVutl0jx4lEC%2FqMJyJtna4dKpFroYGdjhIwTQCGhnTyrIEQcw%3D%3D&Expires=1781646795)

| Nivel router | Motor VRAM | Activo con |
|---|---|---|
| `chat` / `instantaneo` | TabbAPI EXL2 `:5000` | `ai_cluster` (default) |
| `agil` | SGLang `:30000` | `ai_cluster --sglang` |
| `profundo` / `phi-mayor-precision` | Ollama GPU `:11434` | siempre |
| `masivo` | Ollama GPU `:11434` | siempre |

Ollama GPU con DeepSeek R1 y Phi4-Reasoning nunca se ve afectado por el swap — siempre está disponible independientemente del modo. El intercambio solo afecta al nivel `chat`/`instantaneo` (TabbAPI) frente al nivel `agil` (SGLang). [ppl-ai-file-upload.s3.amazonaws](https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/48708411/7a2f9443-1ef1-47c4-8c84-9c05ddd1fffb/orchestrator_router_V14.py?AWSAccessKeyId=ASIA2F3EMEYET2DLZV2C&Signature=cVUltQeX%2Bg5M0pCdxTC%2FzxtNuEs%3D&x-amz-security-token=IQoJb3JpZ2luX2VjELX%2F%2F%2F%2F%2F%2F%2F%2F%2F%2FwEaCXVzLWVhc3QtMSJHMEUCIGA2M%2FpXsKZXzW5Q8NzD9V6TZj2eOX0yg8f3dl%2BRaBNJAiEA%2BZAcamk33qK3PY7T3hjjEdGrh0txAeLSfwYfbR4XKREq8wQIfhABGgw2OTk3NTMzMDk3MDUiDBHvUNY%2FAezzvIS1pSrQBLxL2uwy7bnoXQRYdt%2Fzj%2FHJCNwZl4n8iy8%2FbCTBullz5wGvH98Ue6KM9JJ0wn%2BdPo8T4BlVVfAxoX3tvcYKxAMrGYYu%2BCvI1IQlUfdA6CvJ1z%2F1SKCzwiC2AP0WNwh8a%2BCGnnzAMy0qTaSy2IR6l817KoBsGQcudn3Bl9LbP9MabGieTeh8s0XZJzDYWNFC8%2B6LMKcb1zfJZYFq3%2BrYHrk2djES3cGLyuDz75yVkUjrwLADiql46%2BBB9UpKqG7JxZgWHf9u2%2BCeiDL94mToh5V%2BTpzWHZnzKQ6XvFhCXkW%2B0zce6eqA7%2FT20j3x%2FvfcBEC0rrLu3RmFtTTuusdupL6YaBiIsloZQk6TlLDowyc%2FbW7o5bdDQfF1zx0V%2BW9jl83QxFOIEwVjyXx%2Bulog0%2F5CfCsjbl9ilRpuz91FAiJZcZH%2Btu4gfe0%2BoJhaVPd7CFr7HMVX56Y4PxllYavY7tSKjnLjU%2FuXIhn5HUC2PvZQnWAaz1XF2IQV5caeqFGtr7sb9drG6QPzpmSDv11VT84VRz6Mu%2BGSFJXIvs4SqhCijpXPJeMZTDHIY9%2Beq9FrdDhD0ia1%2FaHzM4G%2BGTEgnoR0ZRKaz%2Bc0kw20LPltoVjGruoXq6MkWrlbIvLXK4nF1HuTkuedgmQtRH15fhq1d%2BtkgY8P6U8dMQMcvnn8dZIn%2BdzdHv86T2u%2FH%2FO71qGMktUVRS08jsgwH09VfOuULD76eDhvaw2L1%2FQk14ypiR4MPFDVp0lg0NsLbm%2FFJMdj5ckTPkTO3Lnjods2vuPe4Vow%2BO%2FG0QY6mAFZ4vPeq99E5llZI%2BBYgRAEbbLGWshbkOQM7pdzJ4sKcwtNRJvxVin69u8qJ6qqeDrKL49KmiB%2FEAHc%2B%2F2e1ZUfbQPfXhhb5Q8B54%2BcxUIfY0yymfqvpw55V7gIREQ3dY%2FaswxtYlpuirnewheC96dNeYqm9TVutl0jx4lEC%2FqMJyJtna4dKpFroYGdjhIwTQCGhnTyrIEQcw%3D%3D&Expires=1781646795)

¿Quieres que genere ya la versión V27 del script con el flag `--sglang` implementado?


---


══════════════════════════════════════════════
  Router V14 (FastAPI + Agent :8000)
══════════════════════════════════════════════
[INFO]  Deteniendo router anterior (PID 802291)…
[INFO]  Router V14 lanzado — PID=807837
[OK]    Router V14 ✔ → http://localhost:8000 (respondió en intento 2)
[OK]    Agent Engine ✔ → /v1/agent/tasks respondiendo

══════════════════════════════════════════════
  Resumen del Cluster V36
══════════════════════════════════════════════

  Modo VRAM:  --sglang (SGLang AWQ activo, TabbAPI detenido)

Servicio                       Puerto       Estado
────────────────────────────── ──────────── ──────
Ollama GPU (main)              :11434       ✔ OK
Ollama CPU (router/emb)        :11435       ✔ OK
TabbAPI ExLlamaV2              :5000        — omitido (modo --sglang)
SGLang                         :30000       ✔ OK
ChromaDB                       :8001        ✔ OK
Obsidian Web UI                :3000        ✔ OK
SearXNG                        :8888        ✔ OK
Router V14 (Agent)             :8000        ✔ OK

Configuración OpenClaw (OpenWebUI):
  API URL:    http://localhost:8000/v1
  Model:      ruteador-auto
  Agent:      http://localhost:8000/v1/agent/tasks

Autonomous Reasoning Agent:
  Crear tarea:     curl -X POST http://localhost:8000/v1/agent/tasks -H 'Content-Type: application/json' -d '{"prompt": "...", "max_iterations": 3}'
  Ver estado:      curl http://localhost:8000/v1/agent/tasks/{task_id}
  Ver resultado:   curl http://localhost:8000/v1/agent/tasks/{task_id}/result
  Stream progreso: curl http://localhost:8000/v1/agent/tasks/{task_id}/stream
  Listar tareas:   curl http://localhost:8000/v1/agent/tasks
  Cancelar:        curl -X DELETE http://localhost:8000/v1/agent/tasks/{task_id}

Comandos útiles:
  Ver logs:         tail -f /home/fcela-ga/ai_cluster/logs/router_v14.log
  Indexar vault:    python3 /home/fcela-ga/ai_cluster/indexar_vault_v6.py
  Reindexar todo:   python3 /home/fcela-ga/ai_cluster/indexar_vault_v6.py --clean
  Métricas router:  curl -s http://localhost:8000/metrics | python3 -m json.tool
  Health check:     curl -s http://localhost:8000/health | python3 -m json.tool
  Detener router:   kill $(cat /home/fcela-ga/ai_cluster/router_v14.pid)
  Parar cluster:    docker stop ollama-gpu-main ollama-cpu-router exllamav2-api sglang-server chromadb obsidian-kb searxng
  Heartbeat chroma: curl -s http://127.0.0.1:8001/api/v1/heartbeat

Flags del script:
  ai_cluster            Arranque estándar (imágenes locales)
  ai_cluster --last     Actualiza imágenes :latest antes de arrancar
  ai_cluster --stop     Para el cluster ordenadamente
  ai_cluster --status   Estado en tiempo real de todos los servicios
  ai_cluster --reindex  Re-indexa el vault Obsidian en ChromaDB
  ai_cluster --warmup   Carga modelos GPU en VRAM
  ai_cluster --exl2     Activa TabbAPI EXL2 (KEEP_ALIVE=0 en Ollama)
  ai_cluster --sglang   Activa SGLang AWQ (para TabbAPI, mem-frac 0.15)
  ai_cluster --help     Muestra la ayuda completa




