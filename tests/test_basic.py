"""
test_basic.py — Pruebas básicas para NexusAgentes Notion Tools API

Ejecutar después de arrancar el servidor:
    uvicorn nexus_notion_tools:app --reload --port 8000

Uso:
    python test_basic.py
"""

import os
import sys

# Configurar encoding para Windows (soporte emojis)
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import requests

BASE_URL = "http://localhost:8000"


def test_health():
    """Test 0: Health check"""
    print("\n" + "=" * 60)
    print("🏥 TEST 0: Health Check")
    print("=" * 60)

    try:
        response = requests.get(f"{BASE_URL}/health", timeout=10)
        print(f"   Status: {response.status_code}")
        data = response.json()
        print(f"   Status: {data['status']}")
        print(f"   Notion connected: {data['notion_connected']}")
        return response.status_code == 200
    except requests.exceptions.ConnectionError:
        print(f"   ❌ ERROR: No se puede conectar a {BASE_URL}")
        print(f"   ¿Está corriendo el servidor?")
        print(f"   Ejecuta: uvicorn nexus_notion_tools:app --reload --port 8000")
        return False
    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return False


def test_search(query: str = "ÉLITE"):
    """Test 1: Búsqueda en Notion"""
    print("\n" + "=" * 60)
    print(f"🔍 TEST 1: Search — query='{query}'")
    print("=" * 60)

    try:
        response = requests.post(
            f"{BASE_URL}/search",
            json={"query": query},
            timeout=30,
        )
        print(f"   Status: {response.status_code}")

        if response.status_code != 200:
            print(f"   ❌ Error: {response.text}")
            return None

        data = response.json()
        results = data.get("data", [])
        print(f"   Resultados encontrados: {len(results)}")

        for i, page in enumerate(results[:5], 1):
            print(f"   {i}. {page['title']}")
            print(f"      ID: {page['id']}")
            print(f"      URL: {page['url']}")

        if len(results) > 5:
            print(f"   ... y {len(results) - 5} más")

        return results

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return None


def test_fetch(page_id: str):
    """Test 2: Leer página completa"""
    print("\n" + "=" * 60)
    print(f"📖 TEST 2: Fetch — page_id='{page_id}'")
    print("=" * 60)

    try:
        response = requests.post(
            f"{BASE_URL}/fetch",
            json={"page_id": page_id},
            timeout=30,
        )
        print(f"   Status: {response.status_code}")

        if response.status_code != 200:
            print(f"   ❌ Error: {response.text}")
            return None

        data = response.json().get("data", {})
        print(f"   Título: {data.get('title', 'N/A')}")
        print(f"   URL: {data.get('url', 'N/A')}")
        print(f"   Creado: {data.get('created_time', 'N/A')}")
        print(f"   Editado: {data.get('last_edited_time', 'N/A')}")
        print(f"   Contenido: {len(data.get('content', ''))} caracteres")

        # Mostrar preview del contenido
        content = data.get("content", "")
        if content:
            preview = content[:300]
            print(f"\n   📝 Preview (primeros 300 chars):")
            print(f"   {preview}...")

        return data

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return None


def test_create(parent_id: str, title: str, content: str):
    """Test 3: Crear página"""
    print("\n" + "=" * 60)
    print(f"✨ TEST 3: Create — title='{title}'")
    print("=" * 60)

    try:
        response = requests.post(
            f"{BASE_URL}/create",
            json={
                "parent_id": parent_id,
                "title": title,
                "content": content,
            },
            timeout=30,
        )
        print(f"   Status: {response.status_code}")

        if response.status_code != 200:
            print(f"   ❌ Error: {response.text}")
            return None

        data = response.json().get("data", {})
        print(f"   ✅ Página creada exitosamente!")
        print(f"   ID: {data.get('id', 'N/A')}")
        print(f"   URL: {data.get('url', 'N/A')}")
        print(f"   Título: {data.get('title', 'N/A')}")
        print(f"   Status: {data.get('status', 'N/A')}")

        return data

    except Exception as e:
        print(f"   ❌ ERROR: {e}")
        return None


def main():
    """Ejecuta todos los tests en secuencia"""
    print("\n" + "🚀" * 10)
    print("   NEXUSAGENTES — NOTION TOOLS API")
    print("   Pruebas básicas de funcionalidad")
    print("🚀" * 10)

    # Test 0: Health check
    if not test_health():
        print("\n❌ Health check falló. Abortando pruebas.")
        sys.exit(1)

    # Test 1: Search
    search_results = test_search("ÉLITE")
    if not search_results:
        print("\n⚠️  Search sin resultados. Probando con query vacía...")
        search_results = test_search("")
        if not search_results:
            print("\n⚠️  No hay páginas disponibles. La integración necesita acceso a páginas.")
            print("   Para compartir una página con la integración 'NexusAgentes':")
            print("   1. Abre una página en Notion")
            print("   2. Click en '...' (menú de página) → 'Add connections'")
            print("   3. Busca y selecciona 'NexusAgentes'")
            print("   4. Vuelve a ejecutar este test\n")
            # Intentar fetch con un ID de ejemplo para probar el endpoint
            print("   Probando endpoint /fetch con un ID de prueba...")
            test_fetch("00000000000000000000000000000000")
            return

    # Test 2: Fetch (usa el primer resultado del search)
    first_page_id = search_results[0]["id"]
    fetch_result = test_fetch(first_page_id)

    # Test 3: Create (usa el primer resultado como parent)
    print("\n" + "=" * 60)
    print("⚠️  TEST 3: Create requiere un parent_id válido")
    print("=" * 60)
    print(f"   Usando parent_id del primer resultado de search:")
    print(f"   {first_page_id}")
    print()

    create_result = test_create(
        parent_id=first_page_id,
        title="🧪 Test — NexusAgentes Bot",
        content="# Prueba\n\nEsta página fue creada automáticamente por NexusAgentes.\n\n## Detalles\n\n- Creado por: NexusAgentes Notion Tools API\n- Fecha: automática\n- Propósito: verificación de funcionamiento\n\n---\n\n### Notas\n\nSi ves esto, la integración funciona correctamente.",
    )

    # Resumen final
    print("\n" + "=" * 60)
    print("📊 RESUMEN DE PRUEBAS")
    print("=" * 60)
    print(f"   ✅ Health: OK" if test_health() else "   ❌ Health: FAIL")
    print(f"   ✅ Search: {len(search_results)} resultados" if search_results else "   ❌ Search: FAIL")
    print(f"   ✅ Fetch: '{fetch_result.get('title', 'N/A')}'" if fetch_result else "   ❌ Fetch: FAIL")
    print(f"   ✅ Create: {'Creada' if create_result else 'FAIL'}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
