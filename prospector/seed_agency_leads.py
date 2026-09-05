"""
Script to extract and seed wholesalers and distributors in Paraná and Santa Fe into the database
with campaign='ai_agency' and status='pending'.
"""
import os
import sys
import re
import time
import urllib.parse
import argparse
import requests
from datetime import datetime

# Add project root to sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.database import SessionLocal
from app.database.models.prospect import Prospect
from prospector.scraper import clean_phone_number

NOMINATIM_QUERIES = [
    ("distribuidora parana entre rios", "Paraná", "distribuidora"),
    ("mayorista parana entre rios", "Paraná", "mayorista"),
    ("ferreteria parana entre rios", "Paraná", "ferreteria"),
    ("corralon parana entre rios", "Paraná", "corralon"),
    ("bulonera parana entre rios", "Paraná", "bulonera"),
    ("repuestos parana entre rios", "Paraná", "repuestos"),
    ("pintureria parana entre rios", "Paraná", "pintureria"),
    ("electricidad parana entre rios", "Paraná", "electricidad"),
    ("distribuidora santa fe argentina", "Santa Fe", "distribuidora"),
    ("mayorista santa fe argentina", "Santa Fe", "mayorista"),
    ("ferreteria santa fe argentina", "Santa Fe", "ferreteria"),
    ("corralon santa fe argentina", "Santa Fe", "corralon"),
    ("bulonera santa fe argentina", "Santa Fe", "bulonera"),
    ("repuestos santa fe argentina", "Santa Fe", "repuestos"),
    ("distribuidora bebidas parana", "Paraná", "bebidas"),
    ("distribuidora limpieza parana", "Paraná", "limpieza"),
    ("distribuidora golosinas parana", "Paraná", "golosinas")
]

def seed_agency_leads(target_count: int = 30):
    db = SessionLocal()
    added_leads = []
    
    print("=" * 80)
    print("🚀 EXTRACTOR Y PROSPECTOR AUTÓNOMO DE DISTRIBUIDORAS (Sofía SDR Agency)")
    print(f"🎯 Meta: Extraer y validar hasta {target_count} distribuidores/mayoristas en Paraná y Santa Fe")
    print("=" * 80)
    
    seen_phones = set(
        p[0] for p in db.query(Prospect.phone).all() if p[0]
    )
    
    headers = {'User-Agent': 'AirControlLeadFinder/1.0 (colomajavier@gmail.com)'}
    
    for query_str, ciudad, tipo in NOMINATIM_QUERIES:
        if len(added_leads) >= target_count:
            break
            
        print(f"\n🔍 Buscando: '{query_str}' ({ciudad})...")
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(query_str)}&format=json&addressdetails=1&extratags=1&limit=50"
        
        try:
            res = requests.get(url, headers=headers, timeout=10)
            if res.status_code == 200:
                items = res.json()
                for it in items:
                    if len(added_leads) >= target_count:
                        break
                        
                    tags = it.get('extratags') or {}
                    raw_phone = tags.get('phone') or tags.get('contact:phone') or tags.get('contact:mobile')
                    if not raw_phone:
                        continue
                        
                    # Split multiple phones if semicolon separated
                    candidate_phones = [p.strip() for p in str(raw_phone).split(";")]
                    valid_phone = None
                    for cp in candidate_phones:
                        cleaned = clean_phone_number(cp)
                        if cleaned and len(cleaned) >= 10:
                            valid_phone = cleaned
                            break
                            
                    if not valid_phone:
                        continue
                        
                    if valid_phone in seen_phones:
                        continue
                        
                    raw_name = it.get('display_name', '').split(',')[0].strip()
                    if not raw_name:
                        continue
                        
                    # Exclude lodging accidental matches
                    if any(bad in raw_name.lower() for bad in ["hotel", "cabaña", "hostel", "apart", "bungalow", "alojamiento"]):
                        continue
                        
                    website = tags.get('website') or tags.get('contact:website') or ''
                    addr_info = it.get('address', {})
                    road = addr_info.get('road', '')
                    num = addr_info.get('house_number', '')
                    address_str = f"{road} {num}".strip() or f"{ciudad}, Argentina"
                    
                    prospect = Prospect(
                        name=raw_name,
                        phone=valid_phone,
                        city=ciudad,
                        campaign="ai_agency",
                        business_type=tipo,
                        status="pending",
                        notes=f"Web: {website} | Dir: {address_str}",
                        conversation_history="[]"
                    )
                    db.add(prospect)
                    db.commit()
                    db.refresh(prospect)
                    
                    seen_phones.add(valid_phone)
                    added_leads.append(prospect)
                    print(f"   ✅ AGREGADO: {prospect.name:<32} | {ciudad:<8} | WA: +{prospect.phone:<15} [{tipo}]")
                    
        except Exception as err:
            print(f"   ⚠️ Error en query: {err}")
            
        time.sleep(0.6)

    print("\n" + "=" * 80)
    print(f"🎉 PROCESO FINALIZADO CON ÉXITO: {len(added_leads)} DISTRIBUIDORAS CARGADAS EN BD")
    print("=" * 80)
    for idx, l in enumerate(added_leads, 1):
        print(f"{idx:02d}. {l.name:<35} | {l.city:<10} | +{l.phone:<15} | {l.business_type}")
    print("=" * 80)
    print("💡 Todas quedaron con estado 'pending' listas para iniciar el primer contacto con Sofía.")
    db.close()
    return len(added_leads)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed agency leads from Nominatim")
    parser.add_argument("--limit", type=int, default=25, help="Max leads to extract and seed")
    args = parser.parse_args()
    seed_agency_leads(target_count=args.limit)
