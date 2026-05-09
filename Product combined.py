import json
import re
import os
from difflib import SequenceMatcher

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
SIRENA_FILE    = os.path.join(BASE_DIR, "sirena_products.json")
PLAZALAMA_FILE = os.path.join(BASE_DIR, "plazalama_products.json")
OUTPUT_FILE    = os.path.join(BASE_DIR, "combined_products.json")

SIMILARITY_THRESHOLD = 0.72

CATEGORY_MAP = {
    "Frutas y Vegetales":          "Frutas y Vegetales",
    "Carnes, pescados y mariscos": "Carnes",
    "Carnes y Mariscos":           "Carnes",
    "Lácteos y Huevos":            "Lácteos y Embutidos",
    "Lácteos y Embutidos":         "Lácteos y Embutidos",
    "Bebidas":                     "Bebidas",
    "Bebidas Alcohólicas":         "Bebidas Alcohólicas",
    "Vinos, licores y cervezas":   "Bebidas Alcohólicas",
    "Panadería y Repostería":      "Panadería",
    "Panadería":                   "Panadería",
    "Quesos y Embutidos":          "Lácteos y Embutidos",
    "Despensa":                    "Despensa",
    "Limpieza y Desechables":      "Limpieza y Hogar",
    "Limpieza y Hogar":            "Limpieza y Hogar",
    "Galletas y Dulces":           "Snacks y Dulces",
    "Snacks":                      "Snacks y Dulces",
    "Picadera":                    "Snacks y Dulces",
    "Mascotas":                    "Mascotas",
    "Congelados":                  "Congelados",
    "Cuidado Personal":            "Cuidado Personal",
    "Belleza y Bienestar":         "Cuidado Personal",
    "Farmacia":                    "Farmacia",
    "Bebés":                       "Bebés",
    "Papeles y Desechables":       "Limpieza y Hogar",
    "Listo para Comer":            "Despensa",
}

def normalize_price(price):
    """Convierte cualquier formato de precio a float limpio."""
    if isinstance(price, (int, float)):
        val = float(price)
        return val if val > 0 else 0.0
    if isinstance(price, str):
        # ✅ Si tiene paréntesis como "RD$169($189)", tomar solo el primer precio
        if '(' in price:
            price = price.split('(')[0]
        # Elimina todo excepto dígitos y punto decimal
        cleaned = re.sub(r'[^\d.]', '', price.replace(',', '.'))
        try:
            val = float(cleaned)
            return val if val > 0 else 0.0
        except:
            return 0.0
    return 0.0

def format_price(price_float):
    return f"RD${price_float:.2f}"

def normalize_name(name):
    name = name.lower().strip()
    replacements = {
        'á':'a','é':'e','í':'i','ó':'o','ú':'u',
        'ä':'a','ë':'e','ï':'i','ö':'o','ü':'u',
        'ñ':'n','ç':'c'
    }
    for k, v in replacements.items():
        name = name.replace(k, v)
    name = re.sub(r'\bpor\s+libras?\b', 'lb', name)
    name = re.sub(r'\bpor\s+unidades?\b', 'und', name)
    name = re.sub(r'\bunidades?\b', 'und', name)
    name = re.sub(r'\blibras?\b', 'lb', name)
    stopwords = ['selecto','selecta','fresco','fresca','natural',
                 'premium','especial','extra','grande','pequeño',
                 'mediano','parafinada','encerada']
    for word in stopwords:
        name = re.sub(rf'\b{word}\b', '', name)
    name = re.sub(r'[^a-z0-9\s]', ' ', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name

def normalize_category(category):
    return CATEGORY_MAP.get(category, category)

def similarity(a, b):
    return SequenceMatcher(None, a, b).ratio()

def load_products(filepath):
    with open(filepath, 'r', encoding='utf-8') as f:
        data = json.load(f)
    return data.get('products', [])

def combine_products(sirena_products, plazalama_products):
    combined    = []
    matched_ids = set()

    # ── Índice Plaza Lama por EAN ──────────────────────────────
    plazalama_por_ean = {}
    for i, p in enumerate(plazalama_products):
        ean = p.get('ean', '').strip()
        if ean:
            plazalama_por_ean[ean] = i

    print(f"  📊 Plaza Lama con EAN: {len(plazalama_por_ean)}/{len(plazalama_products)}")

    # ── Índice Plaza Lama normalizado ──────────────────────────
    plazalama_normalized = []
    for i, p in enumerate(plazalama_products):
        price = normalize_price(p['price'])
        plazalama_normalized.append({
            **p,
            '_normalized_name':     normalize_name(p['name']),
            '_normalized_category': normalize_category(p.get('category', '')),
            '_price_float':         price,
            '_index':               i
        })

    # ── Estadísticas de precios Plaza Lama ────────────────────
    precios_validos = sum(1 for p in plazalama_normalized if p['_price_float'] > 0)
    print(f"  📊 Plaza Lama con precio válido: {precios_validos}/{len(plazalama_products)}")

    matches_por_ean    = 0
    matches_por_nombre = 0
    descartados_precio = 0

    for sirena in sirena_products:
        sirena_ean      = sirena.get('ean', '').strip()
        sirena_name     = normalize_name(sirena['name'])
        sirena_category = normalize_category(sirena.get('category', ''))
        sirena_price    = normalize_price(sirena['price'])

        # ✅ Si el precio de La Sirena es inválido, saltar
        if sirena_price <= 0:
            descartados_precio += 1
            continue

        best_match   = None
        match_method = None

        # ── Paso 1: Match por EAN ──────────────────────────────
        if sirena_ean and sirena_ean in plazalama_por_ean:
            idx = plazalama_por_ean[sirena_ean]
            if idx not in matched_ids:
                candidato = plazalama_normalized[idx]
                # ✅ Solo matchear si Plaza Lama también tiene precio válido
                if candidato['_price_float'] > 0:
                    best_match   = candidato
                    match_method = "ean"
                    matches_por_ean += 1
                else:
                    # EAN match pero precio inválido → producto solo en Sirena
                    matched_ids.add(idx)  # Marcar para no usar en nombre tampoco

        # ── Paso 2: Fallback por nombre ────────────────────────
        if not best_match:
            best_score = 0
            for pl in plazalama_normalized:
                if pl['_index'] in matched_ids:
                    continue
                # ✅ Solo considerar si tiene precio válido
                if pl['_price_float'] <= 0:
                    continue
                if pl['_normalized_category'] != sirena_category:
                    continue
                score = similarity(sirena_name, pl['_normalized_name'])
                if score > best_score and score >= SIMILARITY_THRESHOLD:
                    best_score = score
                    best_match = pl

            if best_match:
                match_method = "nombre"
                matches_por_nombre += 1

        if best_match:
            matched_ids.add(best_match['_index'])
            plazalama_price = best_match['_price_float']
            cheaper_store   = "La Sirena" if sirena_price <= plazalama_price else "Plaza Lama"
            savings         = abs(sirena_price - plazalama_price)

            combined.append({
                "name":         sirena['name'],
                "category":     sirena_category,
                "brand":        sirena.get('brand', ''),
                "imageUrl":     sirena['imageUrl'],
                "ean":          sirena_ean,
                "matchMethod":  match_method,
                "cheaperStore": cheaper_store,
                "savings":      round(savings, 2),
                "prices": {
                    "La Sirena": {
                        "price":     sirena_price,
                        "priceStr":  format_price(sirena_price),
                        "imageUrl":  sirena['imageUrl'],
                        "isCheaper": sirena_price <= plazalama_price
                    },
                    "Plaza Lama": {
                        "price":      plazalama_price,
                        "priceStr":   format_price(plazalama_price),
                        "imageUrl":   best_match['imageUrl'],
                        "productUrl": best_match.get('productUrl', ''),
                        "isCheaper":  plazalama_price < sirena_price
                    }
                }
            })
        else:
            # Solo en La Sirena
            combined.append({
                "name":         sirena['name'],
                "category":     sirena_category,
                "brand":        sirena.get('brand', ''),
                "imageUrl":     sirena['imageUrl'],
                "ean":          sirena_ean,
                "matchMethod":  None,
                "cheaperStore": "La Sirena",
                "savings":      0,
                "prices": {
                    "La Sirena": {
                        "price":     sirena_price,
                        "priceStr":  format_price(sirena_price),
                        "imageUrl":  sirena['imageUrl'],
                        "isCheaper": True
                    }
                }
            })

    # ── Productos solo en Plaza Lama ───────────────────────────
    solo_lama = 0
    for pl in plazalama_normalized:
        if pl['_index'] not in matched_ids:
            pl_price = pl['_price_float']
            # ✅ Solo agregar si tiene precio válido
            if pl_price <= 0:
                continue
            solo_lama += 1
            combined.append({
                "name":         pl['name'],
                "category":     pl['_normalized_category'],
                "brand":        "",
                "imageUrl":     pl['imageUrl'],
                "ean":          pl.get('ean', ''),
                "matchMethod":  None,
                "cheaperStore": "Plaza Lama",
                "savings":      0,
                "prices": {
                    "Plaza Lama": {
                        "price":      pl_price,
                        "priceStr":   format_price(pl_price),
                        "imageUrl":   pl['imageUrl'],
                        "productUrl": pl.get('productUrl', ''),
                        "isCheaper":  True
                    }
                }
            })

    return combined, matches_por_ean, matches_por_nombre, descartados_precio

def main():
    try:
        print("📂 Cargando productos...\n")
        sirena    = load_products(SIRENA_FILE)
        plazalama = load_products(PLAZALAMA_FILE)

        print(f"  La Sirena:  {len(sirena)} productos")
        print(f"  Plaza Lama: {len(plazalama)} productos")
        print(f"\n🔄 Combinando...\n")

        combined, ean_matches, name_matches, descartados = combine_products(sirena, plazalama)

        solo_sirena    = sum(1 for p in combined if 'La Sirena' in p['prices'] and 'Plaza Lama' not in p['prices'])
        solo_plazalama = sum(1 for p in combined if 'Plaza Lama' in p['prices'] and 'La Sirena' not in p['prices'])
        ambas          = sum(1 for p in combined if 'La Sirena' in p['prices'] and 'Plaza Lama' in p['prices'])

        print(f"\n📊 Resultados:")
        print(f"   Matches por EAN:            {ean_matches}")
        print(f"   Matches por nombre:         {name_matches}")
        print(f"   Total en ambas tiendas:     {ambas}")
        print(f"   Solo en La Sirena:          {solo_sirena}")
        print(f"   Solo en Plaza Lama:         {solo_plazalama}")
        print(f"   Descartados (precio 0):     {descartados}")
        print(f"   Total combinado:            {len(combined)}")

        output = {
            "total":        len(combined),
            "matches_ean":  ean_matches,
            "matches_name": name_matches,
            "products":     combined
        }

        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        print(f"\n✅ Guardado en {OUTPUT_FILE}")

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

    input("\nPresiona Enter para salir...")

if __name__ == "__main__":
    main()
