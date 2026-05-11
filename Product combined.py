import json, re, os, sys, requests, warnings, time
from io import BytesIO
from PIL import Image
import imagehash
from rapidfuzz import fuzz
from concurrent.futures import ThreadPoolExecutor

# Silenciar advertencias de Pillow
warnings.filterwarnings("ignore", category=UserWarning)

# --- CONFIGURACIÓN DE CLAVES (DEBEN SER IDÉNTICAS A ANDROID STUDIO) ---
STORES = {
    "sirena": "La Sirena",
    "lama": "Plaza Lama",
    "nacional": "Supermercados Nacional",
    "jumbo": "Jumbo",
    "bravo": "Bravo"
}

BASE_DIR      = os.path.dirname(os.path.abspath(__file__))
SIRENA_FILE   = os.path.join(BASE_DIR, "sirena_products.json")
LAMA_FILE     = os.path.join(BASE_DIR, "plazalama_products.json")
NACIONAL_FILE = os.path.join(BASE_DIR, "nacional_products.json")
JUMBO_FILE    = os.path.join(BASE_DIR, "jumbo_products.json")
BRAVO_FILE    = os.path.join(BASE_DIR, "bravo_products.json")
OUTPUT_FILE   = os.path.join(BASE_DIR, "combined_products.json")
MEMORY_FILE   = os.path.join(BASE_DIR, "visual_memory.json")

SIMILARITY_THRESHOLD = 85
VISUAL_THRESHOLD = 10 
MAX_WORKERS = 30

def clean_p(p):
    try:
        s = str(p).split('(')[0]
        c = re.sub(r'[^\d.]', '', s)
        val = float(c) if c else 0.0
        return val if val > 0 else 0.0
    except: return 0.0

def format_price(p): return f"RD${float(p):,.2f}"

def extract_u(n):
    m = re.search(r'(\d+(?:\.\d+)?)\s*(ml|oz|lb|g|gr|kg|l|und)', str(n).lower())
    if m:
        v, u = float(m.group(1)), m.group(2)
        if u == 'oz': return (round(v * 29.57, 0), 'ml')
        if u == 'lb': return (round(v * 453.6, 0), 'g')
        if u in ['kg', 'l']: return (v * 1000, 'g' if u == 'kg' else 'ml')
        return (v, 'g' if u in ['g','gr'] else 'ml' if u=='ml' else u)
    return ("N/A", "N/A")

def are_units_equivalent(u1, u2):
    if u1 == ("N/A", "N/A") or u2 == ("N/A", "N/A"): return u1 == u2
    if u1[1] != u2[1]: return False
    return abs(u1[0] - u2[0]) <= (max(u1[0], u2[0]) * 0.06)

def map_bravo_category(item):
    n, s = item.get('name', '').lower(), item.get('subCategory', '').lower()
    if any(x in n or x in s for x in ['leche', 'queso', 'yogurt', 'huevo', 'salami']): return "Lácteos y Embutidos"
    if any(x in n or x in s for x in ['carne', 'pollo', 'res', 'cerdo', 'pescado']): return "Carnes"
    if any(x in n or x in s for x in ['fruta', 'vegetal', 'verdura', 'viveres']): return "Frutas y Vegetales"
    if any(x in n or x in s for x in ['limpieza', 'detergente', 'jabon']): return "Limpieza y Hogar"
    if any(x in n or x in s for x in ['refresco', 'jugo', 'agua', 'malta']): return "Bebidas"
    if any(x in n or x in s for x in ['cerveza', 'vino', 'ron', 'alcohol']): return "Bebidas Alcohólicas"
    return "Despensa"

VISUAL_MEMORY = {}
if os.path.exists(MEMORY_FILE):
    try:
        with open(MEMORY_FILE, 'r', encoding='utf-8') as f: VISUAL_MEMORY = json.load(f)
    except: pass

def get_hash(url):
    if not url or url in VISUAL_MEMORY: return imagehash.hex_to_hash(VISUAL_MEMORY[url]) if url in VISUAL_MEMORY else None
    try:
        r = requests.get(url, timeout=5)
        h = imagehash.phash(Image.open(BytesIO(r.content)))
        VISUAL_MEMORY[url] = str(h)
        return h
    except: return None

def are_visually_identical(url1, url2, h1=None):
    if url1 == url2: return True
    h1, h2 = (h1 if h1 else get_hash(url1)), get_hash(url2)
    return (h1 - h2) <= VISUAL_THRESHOLD if h1 and h2 else False

def load_json(f):
    if not os.path.exists(f): return []
    with open(f, 'r', encoding='utf-8') as f: d = json.load(f)
    if isinstance(d, list): return d
    if isinstance(d, dict) and 'products' in d: return d['products']
    return []

def prep(p, store_key):
    p_val = clean_p(p.get('price', 0))
    if store_key == STORES['bravo']: p['category'] = map_bravo_category(p)
    return { **p, '_p': p_val, '_u': extract_u(p.get('name', '')), '_s': store_key }

def combine_all():
    print(f"🚀 INICIANDO COMBINADOR MAESTRO V7.11")
    
    s_raw = [prep(p, STORES['sirena']) for p in load_json(SIRENA_FILE) if clean_p(p.get('price')) > 0]
    l_raw = [prep(p, STORES['lama']) for p in load_json(LAMA_FILE) if clean_p(p.get('price')) > 0]
    n_raw = [prep(p, STORES['nacional']) for p in load_json(NACIONAL_FILE) if clean_p(p.get('price')) > 0]
    j_raw = [prep(p, STORES['jumbo']) for p in load_json(JUMBO_FILE) if clean_p(p.get('price')) > 0]
    b_raw = [prep(p, STORES['bravo']) for p in load_json(BRAVO_FILE) if clean_p(p.get('price')) > 0]

    all_t = l_raw + n_raw + j_raw + b_raw
    print(f"🧬 Sincronizando ADN visual...")
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex: 
        list(ex.map(lambda x: get_hash(x.get('imageUrl')), all_t))
    with open(MEMORY_FILE, 'w', encoding='utf-8') as f: json.dump(VISUAL_MEMORY, f)

    master_list, used_l, used_n, used_j, used_b = [], set(), set(), set(), set()

    def find_m(base, pool, used, b_hash):
        b_u, b_n, b_ean = base['_u'], base['name'], str(base.get('ean','')).strip()
        if b_ean and len(b_ean) > 5:
            for i, c in enumerate(pool):
                if i not in used and str(c.get('ean')) == b_ean: return c, i
        for i, c in enumerate(pool):
            if i not in used and are_units_equivalent(b_u, c['_u']) and fuzz.token_set_ratio(b_n, c['name']) >= SIMILARITY_THRESHOLD:
                if are_visually_identical(base['imageUrl'], c['imageUrl'], b_hash): return c, i
        return None, -1

    print("🔍 Unificando catálogos...")
    for idx, s in enumerate(s_raw):
        sh = get_hash(s['imageUrl'])
        ml, il = find_m(s, l_raw, used_l, sh)
        if ml: used_l.add(il)
        mn, in_ = find_m(s, n_raw, used_n, sh)
        if mn: used_n.add(in_)
        mj, ij = find_m(s, j_raw, used_j, sh)
        if mj: used_j.add(ij)
        mb, ib = find_m(s, b_raw, used_b, sh)
        if mb: used_b.add(ib)

        p_dict = {STORES['sirena']: {"price": s['_p'], "priceStr": format_price(s['_p']), "imageUrl": s['imageUrl']}}
        if ml: p_dict[STORES['lama']] = {"price": ml['_p'], "priceStr": format_price(ml['_p']), "imageUrl": ml['imageUrl'], "productUrl": ml.get('productUrl')}
        if mn: p_dict[STORES['nacional']] = {"price": mn['_p'], "priceStr": format_price(mn['_p']), "imageUrl": mn['imageUrl']}
        if mj: p_dict[STORES['jumbo']] = {"price": mj['_p'], "priceStr": format_price(mj['_p']), "imageUrl": mj['imageUrl']}
        if mb: p_dict[STORES['bravo']] = {"price": mb['_p'], "priceStr": format_price(mb['_p']), "imageUrl": mb['imageUrl']}

        prices_vals = [x['price'] for x in p_dict.values()]
        min_v = min(prices_vals)
        master_list.append({
            "name": s['name'], "category": s['category'], "brand": str(s.get('brand','GENERICO')).upper(),
            "imageUrl": s['imageUrl'], "ean": str(s.get('ean','')), "cheaperStore": [k for k,v in p_dict.items() if v['price']==min_v][0],
            "savings": round(max(prices_vals)-min_v, 2), "prices": {k: {**v, "isCheaper": v['price']==min_v} for k, v in p_dict.items()}
        })
        if idx % 500 == 0: print(f" 🔄 Progreso: {idx}/{len(s_raw)}...")

    print("📦 Restaurando catálogo completo...")
    for label, raw_list, used_set in [("Lama", l_raw, used_l), ("Nacional", n_raw, used_n), ("Jumbo", j_raw, used_j), ("Bravo", b_raw, used_b)]:
        added = 0
        for i, item in enumerate(raw_list):
            if i not in used_set:
                master_list.append({
                    "name": item['name'], "category": item['category'], "brand": str(item.get('brand','GENERICO')).upper(),
                    "imageUrl": item['imageUrl'], "ean": str(item.get('ean','')), "cheaperStore": item['_s'], "savings": 0,
                    "prices": {item['_s']: {"price": item['_p'], "priceStr": format_price(item['_p']), "imageUrl": item['imageUrl'], "isCheaper": True}}
                })
                added += 1
        print(f"   ✅ {label}: +{added} exclusivos.")

    with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
        json.dump({"total": len(master_list), "products": master_list}, f, ensure_ascii=False, indent=2)
    
    print(f"\n✨ PROCESO TERMINADO: {len(master_list)} artículos totales.")

if __name__ == "__main__":
    try: combine_all()
    except Exception as e: print(f"❌ Error: {e}"); import traceback; traceback.print_exc()
    input("\nPresiona Enter...")
