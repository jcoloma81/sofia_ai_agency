import requests
from bs4 import BeautifulSoup
import urllib.parse
import re
import time
import json
import unicodedata
from concurrent.futures import ThreadPoolExecutor

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX = re.compile(r'(?:\+?54\s?)?(?:9\s?)?(?:\d{2,4}\s?[-.\s]?\d{3,4}[-.\s]?\d{3,4})')

DIRECTORY_DOMAINS = [
    'duckduckgo.com', 'google.com', 'wikipedia.org', 'maps.google', 'yelp.com',
    'findglocal.com', 'dentists10.com', 'paginasamarillas', 'yellowpages',
    'cylex', 'mercadolibre', 'tripadvisor', 'booking.com', 'foursquare.com',
    'guia-local', 'habitissimo', 'linkedin.com', 'twitter.com', 'youtube.com',
    'pinterest.com', 'github.com', 'wordpress.com', 'wixsite.com',
    'despegar.com'
]

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
}

def remove_accents(input_str):
    if not input_str:
        return ''
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def clean_phone_number(phone_raw):
    if not phone_raw:
        return None
    digits = re.sub(r'[^\d]', '', str(phone_raw))
    if len(digits) < 7:
        return None
    
    # Strip leading zeros
    digits = re.sub(r'^0+', '', digits)
    
    # Check if Brazil (+55)
    if digits.startswith('55') and len(digits) in (12, 13):
        return digits

    # Check if already starts with 54 (Argentina)
    if digits.startswith('54'):
        if not digits.startswith('549'):
            if len(digits) == 12: # e.g. 54 343 4567890
                digits = '549' + digits[2:]
        return digits if len(digits) >= 11 else None

    # Handle removal of '15' mobile prefix after area code (Argentina):
    for ac in ['343', '342', '341', '11', '3442', '3447', '345']:
        if digits.startswith(ac + '15') and len(digits) >= len(ac) + 2 + 6:
            digits = ac + digits[len(ac)+2:]
            break
            
    if len(digits) == 10: # e.g. 3434567890 (Argentina local mobile/landline)
        digits = '549' + digits
    elif len(digits) == 8 and digits.startswith(('4', '5', '6', '7')):
        digits = '549343' + digits
    elif len(digits) == 11 and digits[2] == '9' and digits[:2] in ['75', '71', '11', '21', '31', '41', '51', '61', '81', '85']:
        # Brazil mobile without country code (DDD + 9 digits, e.g. 75988887777 for Feira de Santana/Bahia)
        digits = '55' + digits
    elif not digits.startswith('549') and not digits.startswith('55') and len(digits) >= 10:
        digits = '549' + digits
        
    return digits

def clean_email_address(email_raw):
    if not email_raw:
        return None
    email = email_raw.lower().strip()
    email = re.sub(r'[.,;:]$', '', email)
    
    if any(email.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.mp4', '.pdf']):
        return None
    if any(bad in email for bad in ['email@email.com', 'correo@correo.com', 'example@', 'sentry.io', 'wix.com', 'domain.com', 'yourname@', 'u003e', 'welcomeargentina']):
        return None
    return email

# -------------------------------------------------------------
# SEED SOURCE 1: WelcomeArgentina Directory
# -------------------------------------------------------------
def get_welcome_argentina_seeds(ciudad_raw):
    clean_c = remove_accents(ciudad_raw).lower().strip()
    slugs = [clean_c.replace(' ', ''), clean_c.replace(' ', '-')]
    base_url = "https://www.welcomeargentina.com"
    
    seeds = []
    visited_urls = set()
    
    for slug in set(slugs):
        sections = [
            f"/{slug}/hoteles.html",
            f"/{slug}/cabanas.html",
            f"/{slug}/alojamientos.html",
            f"/{slug}/hospedajes.html",
            f"/{slug}/apart-hoteles.html",
            f"/{slug}/bungalows.html"
        ]
        
        for sec in sections:
            try:
                r = requests.get(base_url + sec, headers=HEADERS, timeout=8)
                if r.status_code == 200:
                    soup = BeautifulSoup(r.text, 'html.parser')
                    for a in soup.find_all('a', href=True):
                        href = a['href']
                        if href.startswith(f'/{slug}/') and href.endswith('.html') and not any(x in href for x in ['paseos', 'gastronomia', 'servicios', 'fotos', 'ubicacion', 'clima', 'comollegar', 'historia', 'mapa', 'lodging', 'alquilerdeautos', 'blog']):
                            full_url = base_url + href
                            if full_url not in visited_urls:
                                visited_urls.add(full_url)
                                name = a.get_text(strip=True) or href.split('/')[-1].replace('.html', '').replace('-', ' ').title()
                                seeds.append({
                                    'name': name,
                                    'detail_url': full_url,
                                    'source': 'WelcomeArgentina'
                                })
            except Exception:
                pass
    return seeds

# -------------------------------------------------------------
# SEED SOURCE 2: DuckDuckGo Web Search Results
# -------------------------------------------------------------
def get_ddg_search_seeds(rubro, ciudad):
    ciudad_clean = remove_accents(ciudad)
    queries = [
        f"{rubro} {ciudad_clean} Argentina contacto telefono email",
        f"alojamientos cabañas aparts {ciudad_clean} Argentina contacto",
        f"hospedaje hotel hostel {ciudad_clean} contacto whatsapp"
    ]
    
    seeds = []
    visited_links = set()
    
    for q in queries:
        try:
            url = "https://html.duckduckgo.com/html/"
            res = requests.post(url, headers=HEADERS, data={'q': q}, timeout=8)
            if res.status_code == 200:
                soup = BeautifulSoup(res.text, 'html.parser')
                for r in soup.select('.result'):
                    title_tag = r.select_one('.result__title')
                    snippet_tag = r.select_one('.result__snippet')
                    url_tag = r.select_one('.result__url')
                    
                    if title_tag:
                        title = title_tag.get_text(strip=True)
                        link = url_tag.get_text(strip=True) if url_tag else ''
                        snippet = snippet_tag.get_text(strip=True) if snippet_tag else ''
                        
                        if link and not link.startswith('http'):
                            link = 'https://' + link
                            
                        if link and not any(dir_dom in link.lower() for dir_dom in DIRECTORY_DOMAINS):
                            if link not in visited_links:
                                visited_links.add(link)
                                seeds.append({
                                    'name': title,
                                    'official_web': link,
                                    'snippet': snippet,
                                    'source': 'DuckDuckGo Web Search'
                                })
        except Exception:
            pass
    return seeds

# -------------------------------------------------------------
# SEED SOURCE 3: OpenStreetMap / Nominatim API
# -------------------------------------------------------------
def get_nominatim_seeds(rubro, ciudad):
    ciudad_clean = remove_accents(ciudad)
    queries = [f"{rubro} {ciudad_clean} Argentina"]
    if any(k in rubro.lower() for k in ["hotel", "hospedaje", "alojamiento", "cabana", "apart", "hostel"]):
        queries.extend([
            f"hotel {ciudad_clean} Argentina",
            f"hostel {ciudad_clean} Argentina",
            f"cabana {ciudad_clean} Argentina",
            f"apart {ciudad_clean} Argentina"
        ])
    seeds = []
    seen = set()
    
    for q in queries:
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q)}&format=json&addressdetails=1&extratags=1&limit=50"
        try:
            res = requests.get(url, headers={'User-Agent': 'AirControlProspector/1.0'}, timeout=8)
            if res.status_code == 200:
                items = res.json()
                for item in items:
                    if not isinstance(item, dict):
                        continue
                    display_name = item.get('display_name', '')
                    name = display_name.split(',')[0].strip()
                    if name and name not in seen:
                        seen.add(name)
                        tags = item.get('extratags') or {}
                        addr = item.get('address') or {}
                        seeds.append({
                            'name': name,
                            'osm_tags': tags,
                            'osm_addr': addr,
                            'source': 'OpenStreetMap'
                        })
        except Exception:
            pass
    return seeds

# -------------------------------------------------------------
# DEEP SCRAPER FOR A SEED ITEM
# -------------------------------------------------------------
def scrape_seed_details(seed, rubro, ciudad):
    if not seed or not isinstance(seed, dict):
        return None
        
    name = str(seed.get('name') or '').strip()
    if not name:
        return None
        
    osm_tags = seed.get('osm_tags') or {}
    osm_addr = seed.get('osm_addr') or {}
    official_web = seed.get('official_web') or seed.get('detail_url') or osm_tags.get('website') or ''
    
    phones = set()
    emails = set()
    address = f"{ciudad}, Argentina"
    whatsapp_found = ""
    instagram = ""
    
    # 1. Si viene de WelcomeArgentina
    if seed.get('source') == 'WelcomeArgentina' and seed.get('detail_url'):
        try:
            r = requests.get(seed['detail_url'], headers=HEADERS, timeout=8)
            if r.status_code == 200:
                s = BeautifulSoup(r.text, 'html.parser')
                h1 = s.find('h1')
                if h1:
                    name = h1.get_text(strip=True)
                txt = s.get_text()
                
                for ph in PHONE_REGEX.findall(txt):
                    cp = clean_phone_number(ph)
                    if cp:
                        phones.add(cp)
                for mail in EMAIL_REGEX.findall(r.text):
                    ce = clean_email_address(mail)
                    if ce:
                        emails.add(ce)
                        
                addr_m = re.search(r'(?:Dirección|Ubicación|Calle):\s*([^\n\r]+)', txt, re.IGNORECASE)
                if addr_m:
                    address = addr_m.group(1).strip()
        except Exception:
            pass

    # 2. Si viene de OpenStreetMap
    elif seed.get('source') == 'OpenStreetMap':
        p = osm_tags.get('phone') or osm_tags.get('contact:phone') or osm_tags.get('contact:mobile')
        e = osm_tags.get('email') or osm_tags.get('contact:email')
        if p:
            cp = clean_phone_number(p)
            if cp:
                phones.add(cp)
        if e:
            ce = clean_email_address(e)
            if ce:
                emails.add(ce)
        st = osm_addr.get('road', '')
        num = osm_addr.get('house_number', '')
        if st:
            address = f"{st} {num}".strip()

    # 3. Si viene de búsqueda web DuckDuckGo (snippet u oficial)
    if seed.get('snippet'):
        snippet = seed['snippet']
        for ph in PHONE_REGEX.findall(snippet):
            cp = clean_phone_number(ph)
            if cp:
                phones.add(cp)
        for mail in EMAIL_REGEX.findall(snippet):
            ce = clean_email_address(mail)
            if ce:
                emails.add(ce)

    # 4. Crawling profundo del sitio web oficial si existe
    if official_web and official_web.startswith('http'):
        try:
            r = requests.get(official_web, headers=HEADERS, timeout=8)
            if r.status_code == 200:
                s = BeautifulSoup(r.text, 'html.parser')
                txt = s.get_text()
                
                for mail in EMAIL_REGEX.findall(r.text):
                    ce = clean_email_address(mail)
                    if ce:
                        emails.add(ce)
                for ph in PHONE_REGEX.findall(txt):
                    cp = clean_phone_number(ph)
                    if cp:
                        phones.add(cp)
                        
                for a in s.find_all('a', href=True):
                    href = a['href']
                    if href.startswith('mailto:'):
                        ce = clean_email_address(href.replace('mailto:', '').split('?')[0])
                        if ce:
                            emails.add(ce)
                    elif href.startswith('tel:'):
                        cp = clean_phone_number(href.replace('tel:', ''))
                        if cp:
                            phones.add(cp)
                    elif any(x in href for x in ['wa.me/', 'api.whatsapp.com/']):
                        whatsapp_found = href
                    elif 'instagram.com/' in href and not instagram:
                        if not any(x in href for x in ['/p/', '/explore/']):
                            instagram = href
        except Exception:
            pass

    # WhatsApp principal
    primary_wa = list(phones)[0] if phones else ""
    if not primary_wa and whatsapp_found:
        m = re.search(r'\d{8,15}', whatsapp_found)
        if m:
            primary_wa = m.group(0)

    wa_formatted = clean_phone_number(primary_wa) if primary_wa else ""
    wa_link = f"https://wa.me/{wa_formatted}" if wa_formatted else ""

    lower_n = name.lower()
    if 'hostel' in lower_n or 'albergue' in lower_n:
        tipo = 'Hostel'
    elif 'cabaña' in lower_n or 'bungalow' in lower_n or 'chalet' in lower_n:
        tipo = 'Cabaña / Bungalow'
    elif 'apart' in lower_n or 'departamento' in lower_n or 'ph' in lower_n or 'temporal' in lower_n:
        tipo = 'Alquiler Temporario / Apart'
    else:
        tipo = 'Hotel / Hospedaje'

    return {
        'nombre': name,
        'tipo': tipo,
        'ciudad': ciudad,
        'direccion': address,
        'telefonos': list(phones),
        'whatsapp_numero': wa_formatted,
        'whatsapp_link': wa_link,
        'emails': list(emails),
        'website': official_web or '',
        'instagram': instagram or ''
    }

# -------------------------------------------------------------
# MAIN GENERATOR
# -------------------------------------------------------------
def prospect_leads_generator(rubro, ciudad):
    yield {"type": "status", "message": f"🌐 Unificando fuentes de datos para {rubro} en {ciudad}..."}
    
    seeds = []
    
    # 1. Seeding desde WelcomeArgentina
    wa_seeds = get_welcome_argentina_seeds(ciudad)
    seeds.extend(wa_seeds)
    yield {"type": "status", "message": f"📍 Directivos locales (WelcomeArgentina): {len(wa_seeds)} prospectos."}
    
    # 2. Seeding desde Búsqueda Web (DuckDuckGo)
    web_seeds = get_ddg_search_seeds(rubro, ciudad)
    seeds.extend(web_seeds)
    yield {"type": "status", "message": f"🌐 Búsqueda Web Profunda: {len(web_seeds)} sitios oficiales de {ciudad}."}
    
    # 3. Seeding desde OpenStreetMap (Nominatim)
    osm_seeds = get_nominatim_seeds(rubro, ciudad)
    seeds.extend(osm_seeds)
    yield {"type": "status", "message": f"🗺️ OpenStreetMap / Nominatim: {len(osm_seeds)} fichas geolocalizadas."}
    
    # Deduplicar semillas por nombre normalizado
    unique_seeds = []
    seen_names = set()
    
    bad_keywords = [
        'hotelesen', 'cabanasen', 'alojamientos', 'mapade', 'galeria', 'historia',
        'espanol', 'english', 'alquilerdeautos', 'blogdeturismo', 'comollegar',
        'servicios', 'fotos', 'lodging'
    ]
    
    for s in seeds:
        if not s or not isinstance(s, dict):
            continue
        raw_n = s.get('name') or ''
        norm_name = remove_accents(raw_n).lower()
        norm_name = re.sub(r'[^\w]', '', norm_name)
        if norm_name and len(norm_name) > 3:
            if any(bad in norm_name for bad in bad_keywords):
                continue
            if norm_name not in seen_names:
                seen_names.add(norm_name)
                unique_seeds.append(s)

    yield {"type": "status", "message": f"🎯 TOTAL UNIFICADO Y DEDUPLICADO: {len(unique_seeds)} ESTABLECIMIENTOS EN {ciudad.upper()}."}

    processed_leads = []
    for idx, seed in enumerate(unique_seeds, 1):
        yield {"type": "progress", "current": idx, "total": len(unique_seeds), "name": seed.get('name', '')}
        try:
            lead = scrape_seed_details(seed, rubro, ciudad)
            if lead and isinstance(lead, dict):
                processed_leads.append(lead)
                yield {"type": "lead", "lead": lead}
        except Exception as e:
            print(f"Error procesando lead: {e}")

    yield {"type": "complete", "total": len(processed_leads), "leads": processed_leads}
