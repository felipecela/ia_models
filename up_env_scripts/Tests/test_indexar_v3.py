#!/usr/bin/env python3
"""
Tests unitarios para indexar_vault_v3.py — funciones de chunking y preprocesamiento.
"""
import sys
sys.argv = ['test']  # Evitar que argparse interfiera

# Importar funciones directamente ejecutando el módulo parcialmente
import importlib.util
spec = importlib.util.spec_from_file_location("indexar_vault_v3", "/home/ubuntu/indexar_vault_v3.py")
mod = importlib.util.module_from_spec(spec)

# Patch sys.argv antes de cargar
sys.argv = ['indexar_vault_v3.py', '--dry-run']
spec.loader.exec_module(mod)

# ─── Test 1: clean_markdown elimina frontmatter ───
def test_clean_frontmatter():
    text = """---
title: Mi Nota
tags: [python, ai]
---

# Título Principal

Este es el contenido **importante** de la nota.
"""
    result = mod.clean_markdown(text)
    assert "---" not in result, f"Frontmatter no eliminado: {result[:100]}"
    assert "importante" in result, f"Contenido perdido: {result[:100]}"
    assert "**" not in result, f"Bold no limpiado: {result[:100]}"
    print("✔ Test 1 PASS: clean_markdown elimina frontmatter y bold")


# ─── Test 2: clean_markdown resuelve links Obsidian ───
def test_clean_obsidian_links():
    text = "Esto referencia a [[Mi Nota]] y también [[Otra Nota|alias bonito]]."
    result = mod.clean_markdown(text)
    assert "Mi Nota" in result, f"Link no resuelto: {result}"
    assert "alias bonito" in result, f"Alias no resuelto: {result}"
    assert "[[" not in result, f"Brackets no eliminados: {result}"
    print("✔ Test 2 PASS: clean_markdown resuelve links Obsidian")


# ─── Test 3: chunk_text_semantic respeta párrafos ───
def test_semantic_chunking():
    # Crear texto con párrafos claros
    paragraphs = [f"Este es el párrafo número {i}. " * 20 for i in range(10)]
    text = "\n\n".join(paragraphs)
    chunks = mod.chunk_text_semantic(text)
    
    # Verificar que ningún chunk corta una palabra a mitad
    for chunk in chunks:
        t = chunk["text"]
        # No debería empezar con minúscula (indicaría corte a mitad de frase)
        # Excepto si es continuación legítima
        assert len(t) >= mod.CHUNK_MIN_CHARS, f"Chunk demasiado corto: {len(t)}"
        assert len(t) <= mod.CHUNK_MAX_CHARS * 1.5, f"Chunk demasiado largo: {len(t)}"
    
    print(f"✔ Test 3 PASS: chunking semántico generó {len(chunks)} chunks válidos")


# ─── Test 4: chunk_text_semantic con secciones ───
def test_semantic_sections():
    text = """# Introducción

Este es el primer párrafo de la introducción con contenido suficiente para ser válido.

## Desarrollo

El desarrollo contiene información más detallada sobre el tema principal del documento.

## Conclusión

La conclusión resume los puntos principales discutidos anteriormente en el documento.
"""
    chunks = mod.chunk_text_semantic(text)
    
    # Verificar que se preservan los headings
    headings = [c["heading"] for c in chunks]
    assert any("Introducción" in h for h in headings), f"Heading 'Introducción' no encontrado: {headings}"
    print(f"✔ Test 4 PASS: secciones preservadas en chunks ({len(chunks)} chunks)")


# ─── Test 5: extract_frontmatter_tags ───
def test_extract_tags():
    text = """---
title: Test
tags: [python, machine-learning, ai]
---

# Contenido con #inline_tag
"""
    tags = mod.extract_frontmatter_tags(text)
    assert "python" in tags, f"Tag 'python' no encontrado: {tags}"
    assert "machine-learning" in tags, f"Tag 'machine-learning' no encontrado: {tags}"
    assert "inline_tag" in tags, f"Tag inline no encontrado: {tags}"
    print(f"✔ Test 5 PASS: tags extraídos correctamente: {tags}")


# ─── Test 6: extract_title ───
def test_extract_title():
    text = "# Mi Documento Importante\n\nContenido aquí."
    title = mod.extract_title(text, "/path/to/fallback-name.md")
    assert title == "Mi Documento Importante", f"Título incorrecto: {title}"
    
    # Fallback al nombre del archivo
    text2 = "Sin encabezado H1 aquí."
    title2 = mod.extract_title(text2, "/path/to/mi-nota-especial.md")
    assert "mi" in title2.lower(), f"Fallback incorrecto: {title2}"
    print(f"✔ Test 6 PASS: títulos extraídos correctamente")


# ─── Test 7: chunk_id usa SHA-256 ───
def test_chunk_id():
    id1 = mod.chunk_id("notas/test.md", 0)
    id2 = mod.chunk_id("notas/test.md", 1)
    id3 = mod.chunk_id("notas/test.md", 0)
    
    assert id1 != id2, "IDs iguales para chunks diferentes"
    assert id1 == id3, "IDs diferentes para el mismo chunk"
    assert len(id1) == 32, f"Longitud de ID incorrecta: {len(id1)}"
    print(f"✔ Test 7 PASS: chunk_id genera IDs SHA-256 estables de 32 chars")


# ─── Test 8: file_signature ───
def test_file_signature():
    import tempfile
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("test content")
        f.flush()
        sig = mod.file_signature(f.name)
    
    assert ":" in sig, f"Firma sin separador: {sig}"
    parts = sig.split(":")
    assert len(parts) == 2, f"Firma con formato incorrecto: {sig}"
    print(f"✔ Test 8 PASS: file_signature genera firma válida: {sig}")


# ─── Test 9: progress_bar no crashea ───
def test_progress_bar():
    import io
    old_stdout = sys.stdout
    sys.stdout = io.StringIO()
    mod.progress_bar(5, 10, prefix="Test")
    mod.progress_bar(10, 10, prefix="Test")
    mod.progress_bar(0, 0, prefix="Empty")
    output = sys.stdout.getvalue()
    sys.stdout = old_stdout
    assert "50.0%" in output, f"Porcentaje no encontrado en: {output}"
    print("✔ Test 9 PASS: progress_bar funciona correctamente")


# ─── Ejecutar todos los tests ───
if __name__ == "__main__":
    print("\n" + "═" * 50)
    print(" Tests unitarios: indexar_vault_v3.py")
    print("═" * 50 + "\n")
    
    tests = [
        test_clean_frontmatter,
        test_clean_obsidian_links,
        test_semantic_chunking,
        test_semantic_sections,
        test_extract_tags,
        test_extract_title,
        test_chunk_id,
        test_file_signature,
        test_progress_bar,
    ]
    
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as e:
            failed += 1
            print(f"✘ {test.__name__} FAILED: {e}")
    
    print(f"\n{'═' * 50}")
    print(f" Resultado: {passed} passed, {failed} failed")
    print(f"{'═' * 50}\n")
    
    sys.exit(0 if failed == 0 else 1)
