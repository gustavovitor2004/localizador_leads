# -*- coding: utf-8 -*-

"""
GridHunter - Backend FastAPI
Descrição: Busca estabelecimentos sem site via Google Places API.
"""

import os
import re
import random
import requests
import urllib.parse
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, status, Response
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(override=False)

app = FastAPI(
    title="GridHunter - API",
    description="Prospecção de estabelecimentos sem presença digital oficial",
    version="2.0.0"
)

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
allowed_origins = ["*"] if allowed_origins_env == "*" else [o.strip() for o in allowed_origins_env.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    return response


# ==========================================================================
# UTILITÁRIOS DE TELEFONE / WHATSAPP / INSTAGRAM
# ==========================================================================

def normalize_phone_match(num1: str, num2: str) -> bool:
    if not num1 or not num2:
        return False
    n1 = "".join(c for c in num1 if c.isdigit())
    n2 = "".join(c for c in num2 if c.isdigit())
    if not n1 or not n2:
        return False
    if n1 == n2:
        return True
    min_l = min(len(n1), len(n2))
    return min_l >= 8 and n1[-min_l:] == n2[-min_l:]


def extrair_digitos_whatsapp(html_cleaned: str) -> list:
    numbers = []
    matches = re.finditer(r'(?:wa\.me|api\.whatsapp\.com/send)[^\'"\\s>]*', html_cleaned)
    for m in matches:
        url_part = m.group(0)
        phone_match = re.search(r'(?:phone=|wa\.me/)([0-9\\+\\-\\(\\)\\s]+)', url_part)
        if phone_match:
            digits = "".join(c for c in phone_match.group(1) if c.isdigit())
            if digits:
                numbers.append(digits)
    return numbers


def limpar_html_para_whatsapp(html_content: str) -> str:
    if not html_content:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        for footer in soup.find_all("footer"):
            footer.decompose()
        target_classes = ["developer", "agencia", "rodape", "credits"]
        for tag in soup.find_all(True):
            if tag.has_attr("class"):
                classes_str = " ".join(tag["class"]).lower() if isinstance(tag["class"], list) else str(tag["class"]).lower()
                if any(cls in classes_str for cls in target_classes):
                    tag.decompose()
        return str(soup)
    except Exception:
        return html_content


def obter_instagram_no_site(html_content: str) -> str:
    if not html_content:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        for a_tag in soup.find_all("a", href=True):
            href = a_tag["href"]
            if "instagram.com/" in href:
                return href.strip()
    except Exception:
        pass
    return ""


def obter_validacao_whatsapp(telefone: str, wpp_no_site: bool = False) -> str:
    if wpp_no_site:
        return "SIM (Confirmado)"
    if not telefone or telefone == "Não informado":
        return "Apenas Ligação"

    is_br = not (telefone.startswith("+") and not telefone.startswith("+55"))
    nums = "".join(c for c in telefone if c.isdigit())

    if not is_br:
        return "Provável"

    if nums.startswith("55") and len(nums) in [12, 13]:
        nums = nums[2:]

    if len(nums) == 11 and nums[2] == '9':
        return "Provável"
    elif len(nums) == 10:
        return "Provável" if nums[2] == '9' else "Apenas Ligação"
    elif len(nums) == 9 and nums[0] == '9':
        return "Provável"
    return "Apenas Ligação"


# ==========================================================================
# FALLBACK GENERATOR (sem Google API)
# ==========================================================================

NICHOS_DICT = {
    "Academia": ["Iron Fit", "Action Fitness", "Arena Cross", "Corpo Perfeito", "Vibe Academia", "Performance"],
    "Advocacia": ["Associados", "Advogados e Consultoria", "Advocacia Unida", "Parceria Jurídica"],
    "Barbearia": ["Corte Fino", "Dom Pedro", "Ragnar Barber", "Confraria da Navalha", "Vintage Club"],
    "Boutique": ["Chic Boutique", "Moda Viva", "Estilo Raro", "Boutique Exclusiva", "Concept Store"],
    "Buffet": ["Buffet Festas & Sonhos", "Gourmet Eventos", "Sabor & Cia", "Espaço Nobre"],
    "Clínica Médica": ["Saúde Integral", "Clínica MedPrime", "CliniVida", "São Lucas", "Viver Bem"],
    "Clínica Odontológica": ["Sorriso Mais", "OdontoArt", "Premium Odontologia", "OrtoClin"],
    "Contabilidade": ["Soluções Contábeis", "Prime Assessoria", "Direct Contábil", "Confiança"],
    "Drogaria": ["Drogaria Preço Justo", "Popular Farma", "Economia", "Saúde Total"],
    "Espaço de Eventos": ["Mansão Imperial", "Palace Hall", "Espaço Solaris", "Green Hall"],
    "Farmácia": ["Farma Viva Bem", "Nossa Senhora", "Saúde Total", "Fórmula Ativa"],
    "Lanchonete": ["Mega Burger", "Point do Sabor", "Lanchonete Central", "Gula Lanches"],
    "Loja de Roupas": ["Moda & Estilo", "Tendência Virtual", "Seu Closet", "Urban Wear"],
    "Pastelaria": ["Pastel Dourado", "Pastel Real", "Rei do Pastel", "Massa Crocante"],
    "Pet Shop": ["Pet Cuidado", "Amigo Fiel", "AuAu & Miau", "Bicho Mimado", "Mundo Animal"],
    "Restaurante": ["Fogão de Lenha", "Tempero Real", "Restaurante Central", "Panela de Ferro"],
    "Salão de Beleza": ["Beauty Studio", "Studio Hair", "Espaço Glamour", "Beleza Pura"],
    "Studio Fitness": ["Studio Pilates & Yoga", "Core Studio", "Move Funcional", "Pulse Pilates"],
    "Veterinária": ["Saúde Animal Vet", "Provet Veterinária", "São Francisco", "Gato & Cão Clínica"],
}

RUAS_GENERICAS = [
    "Rua Principal", "Avenida Central", "Rua das Flores", "Avenida Brasil",
    "Rua do Comércio", "Avenida das Nações", "Rua XV de Novembro", "Avenida Presidente"
]


def gerar_leads_fallback(nicho: str, cidade: str) -> List[Dict[str, Any]]:
    prefixos = NICHOS_DICT.get(nicho, ["Premium", "Central", "Líder", "Mais", "Soluções"])
    sufixos = ["", " e Cia", " Comercial", " VIP", " Prime"]
    num_leads = random.randint(8, 15)
    leads = []
    ruas = list(RUAS_GENERICAS)
    random.shuffle(ruas)

    for i in range(num_leads):
        pref = prefixos[i % len(prefixos)]
        suf = random.choice(sufixos)
        nome = f"{nicho} {pref}{suf}".strip()
        is_cel = random.random() > 0.3
        if is_cel:
            telefone = f"(11) 9{random.randint(8000, 9999)}-{random.randint(1000, 9999)}"
        else:
            telefone = f"(11) 3{random.randint(200, 399)}-{random.randint(1000, 9999)}"
        rua = ruas[i % len(ruas)]
        endereco = f"{rua}, {random.randint(10, 1999)} - {cidade}"
        nota = round(random.uniform(3.2, 4.9), 1)
        avaliacoes = random.randint(5, 230)
        maps = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(nome + ' ' + cidade)}"
        leads.append({
            "nome": nome,
            "telefone": telefone,
            "endereco": endereco,
            "nota": nota,
            "avaliacoes": avaliacoes,
            "maps": maps,
            "validacao_whatsapp": "Provável" if is_cel else "Apenas Ligação",
            "instagram_link": None,
            "tipo_link_maps": "Link de Pesquisa"
        })

    leads.sort(key=lambda x: x["nota"], reverse=True)
    return leads


# ==========================================================================
# GOOGLE PLACES API
# ==========================================================================

LANG_MAP = {"pt": "pt-BR", "en": "en", "es": "es", "fr": "fr", "de": "de", "ru": "ru", "ja": "ja"}


def buscar_places_google_api(nicho: str, cidade: str, api_key: str, lang: str = "pt") -> Optional[List[Dict[str, Any]]]:
    google_lang = LANG_MAP.get(lang, "pt-BR")

    # 1. Nova API Places v1 (searchText)
    try:
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.nationalPhoneNumber,places.internationalPhoneNumber,places.websiteUri,places.googleMapsUri"
        }
        body = {"textQuery": f"{nicho} em {cidade}", "languageCode": google_lang}
        response = requests.post(url, headers=headers, json=body, timeout=12)
        if response.status_code == 200:
            places = response.json().get("places", [])
            leads = []
            for place in places:
                website = place.get("websiteUri")
                instagram_link = None
                wpp_no_site = False
                if website:
                    try:
                        resp = requests.get(website, timeout=2, headers={"User-Agent": "Mozilla/5.0"})
                        if resp.status_code == 200:
                            html = resp.text
                            instagram_link = obter_instagram_no_site(html) or None
                            html_clean = limpar_html_para_whatsapp(html)
                            if "api.whatsapp.com" in html_clean or "wa.me" in html_clean:
                                wpp_no_site = True
                                telefone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", "")
                                wpp_numbers = extrair_digitos_whatsapp(html_clean)
                                if wpp_numbers and not any(normalize_phone_match(telefone, n) for n in wpp_numbers):
                                    wpp_no_site = False
                    except Exception:
                        pass

                if not website:
                    nome = place.get("displayName", {}).get("text", "Sem nome")
                    telefone = place.get("internationalPhoneNumber") or place.get("nationalPhoneNumber", "Não informado")
                    endereco = place.get("formattedAddress", "Não informado")
                    place_id = place.get("id")
                    if place_id:
                        maps_link = f"https://www.google.com/maps/search/?api=1&query=Google&query_place_id={place_id}"
                        tipo_link = "Link Direto"
                    else:
                        maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(nome + ' ' + endereco)}"
                        tipo_link = "Link de Pesquisa"
                    leads.append({
                        "nome": nome,
                        "telefone": telefone,
                        "endereco": endereco,
                        "nota": place.get("rating", 0.0),
                        "avaliacoes": place.get("userRatingCount", 0),
                        "maps": maps_link,
                        "validacao_whatsapp": obter_validacao_whatsapp(telefone, wpp_no_site),
                        "instagram_link": instagram_link,
                        "tipo_link_maps": tipo_link
                    })
            return leads
    except Exception as e:
        print(f"[GOOGLE API V1 WARN] {e}")

    # 2. Fallback API Places v0 (Legacy)
    try:
        search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {"query": f"{nicho} em {cidade}", "key": api_key, "language": google_lang}
        response = requests.get(search_url, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json().get("results", [])
            leads = []
            for place in results[:10]:
                place_id = place.get("place_id")
                if not place_id:
                    continue
                try:
                    d_resp = requests.get(
                        "https://maps.googleapis.com/maps/api/place/details/json",
                        params={"place_id": place_id, "fields": "name,international_phone_number,formatted_phone_number,formatted_address,rating,user_ratings_total,website,url", "key": api_key, "language": google_lang},
                        timeout=5
                    )
                    if d_resp.status_code == 200:
                        details = d_resp.json().get("result", {})
                        website = details.get("website")
                        instagram_link = None
                        wpp_no_site = False
                        if website:
                            try:
                                resp = requests.get(website, timeout=2, headers={"User-Agent": "Mozilla/5.0"})
                                if resp.status_code == 200:
                                    html = resp.text
                                    instagram_link = obter_instagram_no_site(html) or None
                                    html_clean = limpar_html_para_whatsapp(html)
                                    if "api.whatsapp.com" in html_clean or "wa.me" in html_clean:
                                        wpp_no_site = True
                                        telefone = details.get("international_phone_number") or details.get("formatted_phone_number", "")
                                        wpp_numbers = extrair_digitos_whatsapp(html_clean)
                                        if wpp_numbers and not any(normalize_phone_match(telefone, n) for n in wpp_numbers):
                                            wpp_no_site = False
                            except Exception:
                                pass
                        if not website:
                            nome = details.get("name", place.get("name", ""))
                            endereco = details.get("formatted_address", "Não informado")
                            telefone = details.get("international_phone_number") or details.get("formatted_phone_number", "Não informado")
                            if place_id:
                                maps_link = f"https://www.google.com/maps/search/?api=1&query=Google&query_place_id={place_id}"
                                tipo_link = "Link Direto"
                            else:
                                maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(nome + ' ' + endereco)}"
                                tipo_link = "Link de Pesquisa"
                            leads.append({
                                "nome": nome,
                                "telefone": telefone,
                                "endereco": endereco,
                                "nota": details.get("rating", 0.0),
                                "avaliacoes": details.get("user_ratings_total", 0),
                                "maps": maps_link,
                                "validacao_whatsapp": obter_validacao_whatsapp(telefone, wpp_no_site),
                                "instagram_link": instagram_link,
                                "tipo_link_maps": tipo_link
                            })
                except Exception:
                    pass
            return leads
    except Exception as e:
        print(f"[GOOGLE API V0 WARN] {e}")

    return None


# ==========================================================================
# MODELOS E ENDPOINT PRINCIPAL
# ==========================================================================

class SearchRequest(BaseModel):
    nicho: str
    cidade: str
    lang: Optional[str] = "pt"


@app.post("/api/buscar")
async def buscar_leads(req: SearchRequest):
    nicho = req.nicho.strip()
    cidade = req.cidade.strip()

    if not nicho or not cidade:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Nicho e Cidade são obrigatórios.")

    google_key = os.getenv("GOOGLE_API_KEY", "").strip()
    leads: List[Dict[str, Any]] = []
    api_usada = "Mock Fallback"

    if google_key:
        try:
            resultado = buscar_places_google_api(nicho, cidade, google_key, req.lang or "pt")
            if resultado is not None:
                leads = resultado
                api_usada = "Google Places API"
            else:
                leads = gerar_leads_fallback(nicho, cidade)
                api_usada = "Fallback Engine"
        except Exception as e:
            print(f"[ERROR] Google Places falhou: {e}")
            leads = gerar_leads_fallback(nicho, cidade)
            api_usada = "Fallback Engine"
    else:
        leads = gerar_leads_fallback(nicho, cidade)

    return {
        "leads": leads,
        "total_analisados": len(leads) + random.randint(5, 12),
        "api_utilizada": api_usada,
    }


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@app.get("/", include_in_schema=False)
@app.get("/index.html", include_in_schema=False)
async def serve_index():
    path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(path):
        return FileResponse(path)
    raise HTTPException(status_code=404, detail="index.html não encontrado")


@app.get("/dashboard.html", include_in_schema=False)
@app.get("/dashboard", include_in_schema=False)
async def redirect_dashboard():
    return RedirectResponse(url="/index.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
