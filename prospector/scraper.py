import os
import sys
import re
import time
import json
import urllib.parse
import unicodedata
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
import requests
from bs4 import BeautifulSoup
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

# Ensure parent directory is in sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PARENT_DIR = os.path.dirname(BASE_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

try:
    from app.database.database import SessionLocal
    from app.models.prospect import Prospect
except Exception as e:
    SessionLocal = None
    Prospect = None

EMAIL_REGEX = re.compile(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}')
PHONE_REGEX = re.compile(r'(?:\+?54\s?)?(?:9\s?)?(?:\d{2,4}\s?[-.\s]?\d{3,4}[-.\s]?\d{3,4})')

HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
    'Accept-Language': 'es-419,es;q=0.9,en;q=0.8'
}

DIRECTORY_DOMAINS = [
    'google.com', 'wikipedia.org', 'maps.google', 'yelp.com',
    'cylex', 'mercadolibre', 'tripadvisor', 'booking.com', 'foursquare.com',
    'guia-local', 'habitissimo', 'linkedin.com', 'twitter.com', 'youtube.com',
    'pinterest.com', 'github.com', 'wordpress.com', 'wixsite.com'
]

# Area codes for key Argentine cities
CITY_AREA_CODES = {
    'parana': '343',
    'paraná': '343',
    'santa fe': '342',
    'rosario': '341',
    'cordoba': '351',
    'córdoba': '351',
    'buenos aires': '11',
    'caba': '11',
    'concepcion del uruguay': '3442',
    'concepción del uruguay': '3442',
    'colon': '3447',
    'colón': '3447',
    'concordia': '345',
    'gualeguaychu': '3446',
    'gualeguaychú': '3446'
}

def remove_accents(input_str):
    if not input_str:
        return ''
    nfkd_form = unicodedata.normalize('NFKD', str(input_str))
    return "".join([c for c in nfkd_form if not unicodedata.combining(c)])

def clean_phone_number(phone_raw, city="Paraná"):
    """
    Normalizes Argentine phone numbers to E.164 international format:
    e.g. 5493434074434, 5493424690429.
    """
    if not phone_raw:
        return None
    digits = re.sub(r'[^\d]', '', str(phone_raw))
    if len(digits) < 7:
        return None
    
    # Strip leading zeros
    digits = re.sub(r'^0+', '', digits)
    
    city_norm = remove_accents(city).lower().strip()
    default_ac = CITY_AREA_CODES.get(city_norm, '343')
    
    # Check if already starts with 54 (Argentina)
    if digits.startswith('54'):
        if not digits.startswith('549'):
            if len(digits) == 12: # e.g. 54 343 4567890
                digits = '549' + digits[2:]
        return digits if len(digits) >= 11 else None

    # Handle mobile prefix '15' right at start (e.g. 155312953 without area code)
    if digits.startswith('15') and len(digits) == 9:
        digits = default_ac + digits[2:]

    # Handle removal of '15' mobile prefix after known area code:
    for ac in ['343', '342', '341', '11', '351', '3442', '3447', '345', '3446']:
        if digits.startswith(ac + '15') and len(digits) >= len(ac) + 2 + 6:
            digits = ac + digits[len(ac)+2:]
            break
            
    if len(digits) == 10: # e.g. 3434567890 (area code + number)
        digits = '549' + digits
    elif len(digits) == 8 and digits.startswith(('4', '5', '6', '7')):
        # Local landline in Paraná without area code
        digits = '549' + default_ac + digits
    elif len(digits) == 7:
        # Local 7-digit landline without area code
        digits = '549' + default_ac + digits
    elif not digits.startswith('549') and len(digits) >= 10:
        digits = '549' + digits
        
    return digits if len(digits) in (12, 13) else None

def clean_email_address(email_raw):
    if not email_raw:
        return None
    email = email_raw.lower().strip()
    email = re.sub(r'[.,;:\'\"()\[\]{}]+$', '', email)
    
    if any(email.endswith(ext) for ext in ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.css', '.js', '.mp4', '.pdf']):
        return None
    if any(bad in email for bad in ['email@email.com', 'correo@correo.com', 'example@', 'sentry.io', 'wix.com', 'domain.com', 'yourname@', 'u003e', 'username@', 'test@']):
        return None
    return email

def classify_rubro(name, query_rubro="comercio"):
    n = name.lower()
    if any(k in n for k in ['ferreter', 'bulon', 'tornill', 'herramient', 'buloneria', 'bulonera']):
        return 'Ferretería & Bulonera'
    elif any(k in n for k in ['repuesto', 'motor', 'freno', 'embrague', 'taller', 'lubricentro', 'auto part', 'neumat', 'suspens']):
        return 'Repuestos Automotor / Motos'
    elif any(k in n for k in ['distribuidora', 'mayorista', 'distribuidor', 'al por mayor', 'abasto']):
        return 'Distribuidora & Mayorista'
    elif any(k in n for k in ['supermercado', 'autoservicio', 'almacen', 'minimercado', 'comestibles', 'chango']):
        return 'Supermercado & Autoservicio'
    elif any(k in n for k in ['corralon', 'corralón', 'materiales', 'arena', 'ladrill', 'cement']):
        return 'Corralón & Materiales'
    elif any(k in n for k in ['pinturer', 'pintura', 'revestimient']):
        return 'Pinturería'
    elif any(k in n for k in ['sanitario', 'plomer', 'gas', 'grifer']):
        return 'Sanitarios & Plomería'
    elif any(k in n for k in ['electric', 'iluminac', 'cables', 'led']):
        return 'Electricidad & Iluminación'
    elif any(k in n for k in ['bazar', 'plastico', 'limpieza', 'quimic']):
        return 'Bazar & Limpieza Mayorista'
    else:
        return query_rubro.capitalize() if query_rubro else 'Comercio Minorista / Mayorista'

# -------------------------------------------------------------
# SOURCE 1: OpenStreetMap / Nominatim Geolocated API
# -------------------------------------------------------------
def get_nominatim_leads(rubro_query, city="Paraná"):
    city_clean = remove_accents(city)
    q = f"{rubro_query} {city_clean} Argentina"
    url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q)}&format=json&addressdetails=1&extratags=1&limit=50"
    
    headers = {'User-Agent': 'SofiaActualizadorProspector/2.0 (colomajavier@gmail.com)'}
    leads = []
    
    try:
        r = requests.get(url, headers=headers, timeout=8)
        if r.status_code == 200:
            for it in r.json():
                if not isinstance(it, dict):
                    continue
                display_name = it.get('display_name', '')
                raw_name = display_name.split(',')[0].strip()
                if not raw_name or len(raw_name) < 3:
                    continue
                
                tags = it.get('extratags') or {}
                addr_info = it.get('address') or {}
                
                # Check phones
                raw_phone = tags.get('phone') or tags.get('contact:phone') or tags.get('contact:mobile')
                raw_email = tags.get('email') or tags.get('contact:email')
                raw_web = tags.get('website') or tags.get('contact:website')
                
                street = addr_info.get('road', '')
                num = addr_info.get('house_number', '')
                address = f"{street} {num}".strip() or f"{city}, Argentina"
                
                leads.append({
                    'name': raw_name,
                    'city': city,
                    'query_rubro': rubro_query,
                    'raw_phone': raw_phone,
                    'raw_email': raw_email,
                    'website': raw_web or '',
                    'address': address,
                    'source': 'Nominatim OSM'
                })
    except Exception as e:
        print(f"⚠️ Error en Nominatim ({q}): {e}")
        
    return leads

# -------------------------------------------------------------
# SOURCE 2: Bing Web Search (High-Reliability Organic Results)
# -------------------------------------------------------------
def get_bing_search_leads(rubro_query, city="Paraná"):
    city_clean = remove_accents(city)
    q = f"{rubro_query} {city_clean} Entre Rios Argentina contacto telefono" if 'parana' in city_clean.lower() else f"{rubro_query} {city_clean} Santa Fe Argentina contacto telefono"
    url = f"https://www.bing.com/search?q={urllib.parse.quote(q)}"
    
    leads = []
    try:
        r = requests.get(url, headers=HEADERS, timeout=8)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            for item in soup.select('.b_algo'):
                h2 = item.select_one('h2')
                a_tag = h2.select_one('a') if h2 else None
                snippet_p = item.select_one('.b_caption p')
                
                if not a_tag:
                    continue
                
                title = a_tag.get_text(strip=True)
                link = a_tag.get('href', '')
                snippet = snippet_p.get_text(strip=True) if snippet_p else ''
                
                if any(dom in link.lower() for dom in DIRECTORY_DOMAINS):
                    continue
                
                # Extract any phone or email from snippet
                phones_in_snip = PHONE_REGEX.findall(snippet)
                emails_in_snip = EMAIL_REGEX.findall(snippet)
                
                # Clean title (remove pipe suffix like | Home, - Tienda)
                clean_name = re.split(r'[-|–—]', title)[0].strip()
                if len(clean_name) > 3:
                    leads.append({
                        'name': clean_name,
                        'city': city,
                        'query_rubro': rubro_query,
                        'raw_phone': phones_in_snip[0] if phones_in_snip else None,
                        'raw_email': emails_in_snip[0] if emails_in_snip else None,
                        'website': link,
                        'address': f"{city}, Argentina",
                        'source': 'Bing Web Search'
                    })
    except Exception as e:
        print(f"⚠️ Error en Bing Search ({q}): {e}")
        
    return leads

# -------------------------------------------------------------
# SOURCE 3: Deep Website Contact Crawler
# -------------------------------------------------------------
def crawl_website_for_contacts(url, timeout=5):
    """Crawls website looking for WhatsApp links, phone numbers and emails."""
    phones = set()
    emails = set()
    if not url or not url.startswith('http'):
        return phones, emails
        
    try:
        r = requests.get(url, headers=HEADERS, timeout=timeout)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            text = soup.get_text()
            
            # Check emails
            for m in EMAIL_REGEX.findall(r.text):
                em = clean_email_address(m)
                if em:
                    emails.add(em)
                    
            # Check phones
            for p in PHONE_REGEX.findall(text):
                phones.add(p)
                
            # Check links
            for a in soup.find_all('a', href=True):
                href = a['href']
                if href.startswith('mailto:'):
                    em = clean_email_address(href.replace('mailto:', '').split('?')[0])
                    if em:
                        emails.add(em)
                elif 'wa.me/' in href or 'api.whatsapp.com/send' in href:
                    m = re.search(r'\d{8,15}', href)
                    if m:
                        phones.add(m.group(0))
                elif href.startswith('tel:'):
                    phones.add(href.replace('tel:', '').strip())
    except Exception:
        pass
        
    return phones, emails

# -------------------------------------------------------------
# MASTER EXTRACTION PIPELINE
# -------------------------------------------------------------
TARGET_CATEGORIES = [
    # Ferreterías & Buloneras
    "ferreteria",
    "bulonera",
    "tornilleria",
    "herramientas industriales",
    
    # Distribuidoras & Mayoristas
    "distribuidora mayorista",
    "mayorista alimentos bebidas",
    "distribuidora limpieza",
    
    # Repuestos automotor & motos
    "repuestos automotor",
    "repuestos motos",
    "lubricentro",
    
    # Supermercados & Autoservicios
    "supermercado mayorista",
    "autoservicio",
    
    # Construcción & Corralones
    "corralon materiales",
    
    # Pinturerías
    "pintureria",
    
    # Sanitarios & Plomería
    "sanitarios y griferia",
    
    # Electricidad e Iluminación
    "electricidad e iluminacion"
]

def run_prospector_scan(cities=["Paraná", "Santa Fe"], target_leads=30, export_excel=True, save_to_db=True):
    print("=" * 80)
    print("🚀 SOFÍA AI AGENCY — MOTOR DE PROSPECCIÓN COMERCIAL B2B")
    print("🎯 PRODUCTO: SÚPER ACTUALIZADOR PRO v2.0")
    print(f"📍 CIUDADES OBJETIVO: {', '.join(cities).upper()}")
    print(f"🛒 NICHOS: Ferreterías, Mayoristas, Repuestos, Supermercados, Corralones, Sanitarios")
    print(f"🎯 META: Extraer y validar al menos {target_leads} comercios con WhatsApp / Teléfono E.164")
    print("=" * 80)
    
    raw_seeds = []
    seen_keys = set()
    
    # 1. Gather Seeds via Nominatim
    for city in cities:
        print(f"\n🗺️ [NOMINATIM OSM] Escaneando {city}...")
        for cat in TARGET_CATEGORIES:
            seeds = get_nominatim_leads(cat, city=city)
            for s in seeds:
                key = (remove_accents(s['name']).lower().strip(), city.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    raw_seeds.append(s)
            time.sleep(0.3)
            
    # 2. Gather Seeds via Bing Search for high-intent queries
    for city in cities:
        print(f"🌐 [BING SEARCH] Escaneando sitios web y contactos de {city}...")
        for cat in ["distribuidora mayorista", "ferreteria industrial", "repuestos automotor", "corralon", "supermercado mayorista"]:
            seeds = get_bing_search_leads(cat, city=city)
            for s in seeds:
                key = (remove_accents(s['name']).lower().strip(), city.lower())
                if key not in seen_keys:
                    seen_keys.add(key)
                    raw_seeds.append(s)
            time.sleep(0.3)

    print(f"\n📦 TOTAL DE SEMILLAS DETECTADAS: {len(raw_seeds)}")
    print("🔬 Normalizando teléfonos E.164 (+54 9...) y ejecutando crawler de correos y WhatsApp...")
    
    processed_leads = []
    seen_phones = set()
    
    for idx, s in enumerate(raw_seeds, 1):
        name = s['name']
        city = s['city']
        rubro = classify_rubro(name, s.get('query_rubro', ''))
        website = s.get('website', '')
        address = s.get('address', f"{city}, Argentina")
        
        candidate_phones = []
        if s.get('raw_phone'):
            candidate_phones.extend(str(s['raw_phone']).split(';'))
            
        candidate_emails = []
        if s.get('raw_email'):
            candidate_emails.append(s['raw_email'])
            
        # Crawl website if present to harvest extra email/whatsapp
        if website and website.startswith('http'):
            web_phones, web_emails = crawl_website_for_contacts(website, timeout=4)
            candidate_phones.extend(list(web_phones))
            candidate_emails.extend(list(web_emails))
            
        # Normalise phone
        valid_phone = None
        for ph in candidate_phones:
            cleaned = clean_phone_number(ph, city=city)
            if cleaned:
                valid_phone = cleaned
                break
                
        # Normalise email
        valid_email = None
        for em in candidate_emails:
            clem = clean_email_address(em)
            if clem:
                valid_email = clem
                break
                
        # Only retain leads that have at least a phone or an email
        if not valid_phone and not valid_email:
            continue
            
        # Deduplicate by phone
        if valid_phone:
            if valid_phone in seen_phones:
                continue
            seen_phones.add(valid_phone)
            
        wa_link = f"https://wa.me/{valid_phone}" if valid_phone else ""
        
        lead_dict = {
            'id': len(processed_leads) + 1,
            'nombre': name,
            'rubro': rubro,
            'ciudad': city,
            'direccion': address,
            'whatsapp_link': wa_link,
            'telefono': valid_phone or '',
            'email': valid_email or '',
            'website': website or '',
            'estado': 'Pendiente',
            'campana': 'actualizador_pro',
            'fuente': s.get('source', 'Web')
        }
        
        processed_leads.append(lead_dict)
        print(f"  [{len(processed_leads):02d}] ✅ {name:<32} | {city:<10} | WA: +{valid_phone or 'Sin WA':<15} | Email: {valid_email or 'No detectado':<25} | [{rubro}]")
        
        if len(processed_leads) >= target_leads:
            break

    print("\n" + "=" * 80)
    print(f"🎉 EXTRACCIÓN COMPLETADA CON ÉXITO: {len(processed_leads)} COMERCIOS REALES LISTOS")
    print("=" * 80)

    # 3. Save to Database
    if save_to_db and SessionLocal and Prospect:
        try:
            db = SessionLocal()
            existing_db_phones = set(p[0] for p in db.query(Prospect.phone).all() if p[0])
            added_db_count = 0
            for lead in processed_leads:
                if lead['telefono'] and lead['telefono'] not in existing_db_phones:
                    prospect = Prospect(
                        name=lead['nombre'],
                        phone=lead['telefono'],
                        email=lead['email'] or None,
                        city=lead['ciudad'],
                        campaign=lead['campana'],
                        business_type=lead['rubro'],
                        status="pending",
                        notes=f"Dir: {lead['direccion']} | Web: {lead['website']} | Fuente: {lead['fuente']}",
                        conversation_history="[]"
                    )
                    db.add(prospect)
                    existing_db_phones.add(lead['telefono'])
                    added_db_count += 1
            db.commit()
            db.close()
            print(f"💾 Guardados en Base de Datos ({Prospect.__tablename__}): {added_db_count} nuevos prospectos.")
        except Exception as db_err:
            print(f"⚠️ Error guardando en base de datos: {db_err}")

    # 4. Export to Excel
    excel_path = None
    if export_excel and processed_leads:
        excel_path = export_leads_to_excel(processed_leads, cities)

    return processed_leads, excel_path

# -------------------------------------------------------------
# EXCEL EXPORTER (BEAUTIFUL FORMATTED WORKBOOK)
# -------------------------------------------------------------
def export_leads_to_excel(leads, cities):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Prospectos Actualizador PRO"
    
    # Headers
    headers = [
        "ID",
        "Nombre del Comercio",
        "Rubro Comercial",
        "Ciudad",
        "Dirección",
        "WhatsApp Directo (Clic para Chat)",
        "Teléfono E.164",
        "Email Comercial",
        "Sitio Web",
        "Estado",
        "Campaña",
        "Fecha Extracción"
    ]
    
    ws.append(headers)
    
    # Styling
    header_fill = PatternFill(start_color="1B365D", end_color="1B365D", fill_type="solid")
    header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
    data_font = Font(name="Calibri", size=10)
    link_font = Font(name="Calibri", size=10, color="0000FF", underline="single")
    border_side = Side(style="thin", color="E0E0E0")
    thin_border = Border(left=border_side, right=border_side, top=border_side, bottom=border_side)
    
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
    
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for row_idx, lead in enumerate(leads, start=2):
        wa_val = lead.get('whatsapp_link', '')
        
        row_data = [
            lead.get('id'),
            lead.get('nombre'),
            lead.get('rubro'),
            lead.get('ciudad'),
            lead.get('direccion'),
            wa_val if wa_val else "Sin WhatsApp",
            f"+{lead.get('telefono')}" if lead.get('telefono') else "",
            lead.get('email', ''),
            lead.get('website', ''),
            lead.get('estado', 'Pendiente'),
            lead.get('campana', 'actualizador_pro'),
            today_str
        ]
        ws.append(row_data)
        
        # Apply borders and formats
        for col_idx in range(1, len(headers) + 1):
            c = ws.cell(row=row_idx, column=col_idx)
            c.border = thin_border
            c.font = data_font
            
            # Hyperlink for WhatsApp
            if col_idx == 6 and wa_val:
                c.hyperlink = wa_val
                c.font = link_font
                c.alignment = Alignment(horizontal="center")
            elif col_idx in (1, 4, 7, 10, 11, 12):
                c.alignment = Alignment(horizontal="center")
            else:
                c.alignment = Alignment(horizontal="left")
                
    # Auto-adjust column widths
    for col in ws.columns:
        max_len = max(len(str(cell.value or '')) for cell in col)
        col_letter = get_column_letter(col[0].column)
        ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 40)
        
    ws.row_dimensions[1].height = 28
    
    filename = f"prospectos_actualizador_{'_'.join(remove_accents(c).lower() for c in cities)}_{today_str}.xlsx"
    filepath = os.path.join(PARENT_DIR, filename)
    wb.save(filepath)
    print(f"\n📊 Archivo Excel generado con éxito:")
    print(f"👉 {filepath}")
    return filepath

if __name__ == "__main__":
    run_prospector_scan(cities=["Paraná", "Santa Fe"], target_leads=25)
