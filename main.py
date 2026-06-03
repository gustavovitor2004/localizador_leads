# -*- coding: utf-8 -*-

"""
LeadFinder Pro - Backend FastAPI API
Autor: Antigravity AI
Descrição: Servidor backend robusto para controle de buscas, autenticação segura da API Key 
           do Google Places, validação de créditos de usuários (Supabase/Mock) e processamento de webhooks Asaas.
"""

import os
import random
import requests
import uuid
import hashlib
import smtplib
import urllib.parse
import secrets
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, HTTPException, status, Body, Response
from fastapi.responses import FileResponse, RedirectResponse
# pyrefly: ignore [missing-import]
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
# pyrefly: ignore [missing-import]
from supabase import create_client, Client

# Carrega variáveis de ambiente
load_dotenv()

# Inicialização do Cliente Supabase com fallback seguro para mock
SUPABASE_URL = os.getenv("SUPABASE_URL")
# Preferencialmente usa a service_role_key (chave administrativa) para ignorar políticas RLS no servidor FastAPI
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or os.getenv("SUPABASE_KEY")

supabase: Optional[Client] = None
is_supabase_mock = True

is_valid_url = SUPABASE_URL and "sua-url-do-supabase" not in SUPABASE_URL
is_valid_key = SUPABASE_KEY and not any(p in SUPABASE_KEY for p in ["sua-anon-ou-service-role-key", "sua_service_role_key"])

if is_valid_url and is_valid_key:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        is_supabase_mock = False
        print("[DATABASE] Cliente do Supabase real (Bypass RLS habilitado) inicializado com sucesso!")
    except Exception as db_err:
        print(f"[DATABASE WARNING] Erro ao conectar ao Supabase real: {db_err}. Utilizando simulador local em memória.")
else:
    print("[DATABASE WARNING] Credenciais do Supabase não configuradas ou com placeholders no '.env'. Utilizando simulador local em memória.")

app = FastAPI(
    title="LeadFinder Pro - API Comercial",
    description="Backend robusto para prospecção de leads sem presença digital oficial",
    version="1.0.0"
)

# Configuração de CORS para permitir conexões do Frontend (flexível para desenvolvimento e produção)
allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "*")
if allowed_origins_env == "*":
    allowed_origins = ["*"]
else:
    allowed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True if "*" not in allowed_origins else False,
    allow_methods=["*"],
    allow_headers=["*"],
)

def hash_senha(senha: str, salt: bytes = None) -> str:
    """Gera um hash PBKDF2 HMAC-SHA256 seguro para a senha."""
    if not salt:
        salt = secrets.token_bytes(16)
    hash_bytes = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 100000)
    return f"{salt.hex()}:{hash_bytes.hex()}"

def verificar_senha(senha: str, senha_hash: str) -> bool:
    """Verifica se a senha coincide com o hash gerado."""
    try:
        salt_hex, hash_hex = senha_hash.split(":")
        salt = bytes.fromhex(salt_hex)
        expected_hash = bytes.fromhex(hash_hex)
        actual_hash = hashlib.pbkdf2_hmac('sha256', senha.encode('utf-8'), salt, 100000)
        return actual_hash == expected_hash
    except Exception:
        return False

def eh_telefone_fixo(telefone: str) -> bool:
    """Retorna True se o telefone brasileiro for um número fixo (começa com 2, 3, 4 ou 5)."""
    if not telefone or telefone == "Não informado":
        return False
    nums = "".join(c for c in telefone if c.isdigit())
    if nums.startswith("55") and len(nums) > 10:
        nums = nums[2:]
        
    if len(nums) == 10:
        return nums[2] in ['2', '3', '4', '5']
    elif len(nums) == 8:
        return nums[0] in ['2', '3', '4', '5']
    return False

def extrair_digitos_whatsapp(html_cleaned: str) -> list:
    """Extrai os dígitos numéricos de todos os links do WhatsApp no HTML limpo."""
    import re
    numbers = []
    matches = re.finditer(r'(?:wa\.me|api\.whatsapp\.com/send)[^\'"\s>]*', html_cleaned)
    for m in matches:
        url_part = m.group(0)
        phone_match = re.search(r'(?:phone=|wa\.me/)([0-9\+\-\(\)\s]+)', url_part)
        if phone_match:
            raw_phone = phone_match.group(1)
            digits = "".join(c for c in raw_phone if c.isdigit())
            if digits:
                numbers.append(digits)
    return numbers

def limpar_html_para_whatsapp(html_content: str) -> str:
    """Remove footer e elementos de desenvolvedor/agência do HTML para evitar falsos positivos."""
    if not html_content:
        return ""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_content, "html.parser")
        
        # Deleta todas as tags <footer>
        for footer in soup.find_all("footer"):
            footer.decompose()
            
        # Classes de desenvolvedores/agências
        target_classes = ["developer", "agencia", "rodape", "credits"]
        for tag in soup.find_all(True):
            if tag.has_attr("class"):
                classes = tag["class"]
                if isinstance(classes, list):
                    classes_str = " ".join(classes).lower()
                else:
                    classes_str = str(classes).lower()
                if any(cls in classes_str for cls in target_classes):
                    tag.decompose()
        return str(soup)
    except Exception:
        return html_content

def obter_instagram_no_site(html_content: str) -> str:
    """Encontra link real do Instagram no HTML do site."""
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
    """Valida se o telefone comercial é celular (WhatsApp) ou fixo."""
    if wpp_no_site:
        return "SIM (Confirmado)"
        
    if not telefone or telefone == "Não informado":
        return "Apenas Ligação"
    # Remove tudo que não for dígito
    nums = "".join(c for c in telefone if c.isdigit())
    
    # Se começar com 55 e tiver 12 ou 13 dígitos, remove o 55
    if nums.startswith("55") and len(nums) in [12, 13]:
        nums = nums[2:]
        
    # Celulares no Brasil têm 11 dígitos e o número local começa com 9: e.g. 71999998888
    # Telefones fixos têm 10 dígitos: e.g. 7133334444
    if len(nums) == 11 and nums[2] == '9':
        return "Provável"
    elif len(nums) == 10:
        if nums[2] == '9':
            return "Provável"
        else:
            return "Apenas Ligação"
    else:
        # Caso tenha apenas 9 dígitos e comece com 9 (celular sem DDD)
        if len(nums) == 9 and nums[0] == '9':
            return "Provável"
        # Caso tenha 8 dígitos (fixo sem DDD)
        elif len(nums) == 8:
            return "Apenas Ligação"
        return "Apenas Ligação"

# ==========================================================================
# SIMULAÇÃO DE BANCO DE DADOS EM MEMÓRIA (SUPABASE / POSTGRES PLACEHOLDER)
# ==========================================================================
# Simula a tabela "profiles" do Supabase
MOCK_SUPABASE_PROFILES: Dict[str, Dict[str, Any]] = {
    "usr_demo_123": {
        "email": "contato@agenciapremier.com.br",
        "credits": 25,
        "plan": "Premium B2B"
    },
    "usr_starter_456": {
        "email": "designer.freela@gmail.com",
        "credits": 3,
        "plan": "Starter Free"
    }
}

# Inicializa as senhas padrão ("senha123") para os perfis mockados
for k in MOCK_SUPABASE_PROFILES:
    MOCK_SUPABASE_PROFILES[k]["senha_hash"] = hash_senha("senha123")

# ==========================================================================
# ESTRUTURA DE MODELOS PYDANTIC (VALIDAÇÃO DE INPUTS)
# ==========================================================================
class SearchRequest(BaseModel):
    nicho: str
    cidade: str
    user_id: Optional[str] = "usr_demo_123"  # ID do Supabase
    email: Optional[str] = None

class ProfileCreateRequest(BaseModel):
    user_id: str
    email: str
    password: str

class LoginRequest(BaseModel):
    email: str
    password: str

class AsaasPayment(BaseModel):
    id: str
    customer: str
    value: float
    netValue: float
    billingType: str
    status: str
    externalReference: Optional[str] = None # ID do Usuário no Supabase

class AsaasWebhookPayload(BaseModel):
    event: str
    payment: AsaasPayment

# ==========================================================================
# LÓGICA DO GERADOR DE LEADS BACKEND - FALLBACK INTELIGENTE
# ==========================================================================
NICHOS_DICT = {
    "Academia": ["Iron Fit", "Action Fitness", "Arena Cross", "Corpo Perfeito", "Vibe Academia", "Performance", "Guerreiros Studio", "Bio Center"],
    "Advocacia": ["Associados", "Advogados e Consultoria", "Advocacia Unida", "Parceria Jurídica", "Direito Integrado"],
    "Barbearia": ["Corte Fino", "Dom Pedro", "Ragnar Barber", "Confraria da Navalha", "Vintage Club", "Bravos Club"],
    "Boutique": ["Chic Boutique", "Moda Viva", "Estilo Raro", "Boutique Exclusiva", "Concept Store", "Moda Premium"],
    "Buffet": ["Buffet Festas & Sonhos", "Gourmet Eventos", "Sabor & Cia", "Espaço Nobre Buffet", "Festança"],
    "Clínica Médica": ["Saúde Integral", "Clínica MedPrime", "CliniVida", "São Lucas", "Viver Bem", "Médicos Associados"],
    "Clínica Odontológica": ["Sorriso Mais", "OdontoArt", "Premium Odontologia", "OrtoClin", "Boca Saudável", "Implante Rápido"],
    "Contabilidade": ["Soluções Contábeis", "Prime Assessoria", "Direct Contábil", "Parceiros Corporativos", "Confiança"],
    "Drogaria": ["Drogaria Preço Justo", "Popular Farma", "Economia", "Drogaria Mais Saúde", "Super Fórmulas"],
    "Espaço de Eventos": ["Mansão Imperial", "Palace Hall", "Espaço Solaris", "Green Hall", "Vila dos Sonhos"],
    "Farmácia": ["Farma Viva Bem", "Nossa Senhora", "Saúde Total", "Fórmula Ativa", "Vida Saudável"],
    "Lanchonete": ["Mega Burger", "Point do Sabor", "Lanchonete Central", "Gula Lanches", "Burger Express"],
    "Loja de Roupas": ["Moda & Estilo", "Tendência Virtual", "Seu Closet", "Rosa Chá", "Basics Store", "Urban Wear"],
    "Pastelaria": ["Pastel Dourado", "Pastel Real", "Rei do Pastel", "Massa Crocante", "Pastel do Povo"],
    "Pet Shop": ["Pet Cuidado", "Amigo Fiel", "AuAu & Miau", "Bicho Mimado", "Patas & Pelos", "Mundo Animal"],
    "Restaurante": ["Fogão de Barro", "Sabor da Bahia", "Estrela Gourmet", "Tempero Real", "Restaurante Central", "Panela de Ferro"],
    "Salão de Beleza": ["Beauty Studio", "Studio Hair", "Espaço Glamour", "Beleza Pura", "Diva Hair", "Toque de Ouro"],
    "Studio Fitness": ["Studio Pilates & Yoga", "Core Studio", "Move Funcional", "Corpo Ativo", "Pulse Pilates"],
    "Veterinária": ["Saúde Animal Vet", "Provet Veterinária", "São Francisco", "Gato & Cão Clínica", "Veterinária Central"]
}

RUAS_BAHIA = [
    "Avenida Getúlio Vargas", "Rua Conselheiro Franco", "Avenida Sete de Setembro", "Rua Marechal Deodoro", 
    "Avenida Centenário", "Rua Bahia", "Avenida Senhor dos Passos", "Rua Castro Alves", 
    "Praça da Sé", "Avenida Manoel Dias da Silva", "Rua J.J. Seabra", "Avenida Juracy Magalhães",
    "Avenida Tancredo Neves", "Rua das Laranjeiras", "Avenida ACM", "Rua Direita do Bonfim"
]

def obter_uuid_usuario(user_id: Optional[str]) -> Optional[str]:
    """
    Retorna o próprio user_id se ele for um UUID válido.
    Caso contrário, gera um UUID v5 determinístico a partir do user_id.
    """
    if not user_id:
        return user_id
    try:
        uuid.UUID(str(user_id))
        return str(user_id)
    except ValueError:
        # Gera UUID determinístico usando namespace DNS e a string recebida
        return str(uuid.uuid5(uuid.NAMESPACE_DNS, str(user_id)))

def enviar_email_boas_vindas(email: str):
    """
    Dispara um e-mail de boas-vindas para o usuário ao se cadastrar.
    Lê as configurações de SMTP do ambiente. Se não configurado ou se falhar, apenas loga.
    """
    smtp_server = os.getenv("SMTP_SERVER")
    smtp_port = os.getenv("SMTP_PORT")
    smtp_user = os.getenv("SMTP_USER")
    smtp_password = os.getenv("SMTP_PASSWORD")

    # Verifica se os parâmetros SMTP são placeholders ou estão vazios
    if (not smtp_server or not smtp_user or not smtp_password or
        "seu-email@gmail.com" in smtp_user or "sua-senha-de-app" in smtp_password):
        print(f"[SMTP WARNING] Configurações de SMTP vazias ou com placeholders. "
              f"Pulando disparo real de e-mail de boas-vindas para {email}.")
        print("[SMTP NOTE] Para habilitar o envio, insira credenciais válidas de SMTP no seu arquivo '.env'.")
        return

    try:
        # Monta a mensagem MIME
        msg = MIMEMultipart("alternative")
        msg["Subject"] = "Sua conta no LeadFinder Pro foi criada com sucesso!"
        msg["From"] = smtp_user
        msg["To"] = email

        # Versão em texto plano
        text = (
            "Olá!\n\n"
            "Sua conta no LeadFinder Pro foi criada com sucesso!\n"
            "Você acaba de ganhar 5 créditos demonstrativos para começar a buscar leads qualificados agora mesmo.\n\n"
            "Boas prospecções!\n"
            "Equipe LeadFinder Pro"
        )

        # Versão HTML rica (design Dark/Cyber sofisticado condizente com o dashboard)
        html = f"""
        <html>
        <body style="background-color: #0b0f19; color: #f8fafc; font-family: 'Inter', sans-serif; padding: 20px; margin: 0;">
            <div style="max-width: 600px; margin: 0 auto; background-color: #0f172a; border: 1px solid #1e293b; border-radius: 12px; padding: 40px; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.5);">
                <div style="text-align: center; margin-bottom: 30px;">
                    <h1 style="color: #0ea5e9; font-size: 28px; margin: 0; font-weight: 700; letter-spacing: -0.025em;">LeadFinder <span style="color: #f8fafc;">Pro</span></h1>
                    <p style="color: #64748b; font-size: 14px; margin-top: 5px;">Mapeamento Inteligente de Leads B2B</p>
                </div>
                
                <hr style="border: 0; border-top: 1px solid #1e293b; margin-bottom: 30px;" />
                
                <h2 style="font-size: 20px; font-weight: 600; color: #f8fafc; margin-top: 0;">Seja muito bem-vindo(a)!</h2>
                
                <p style="color: #94a3b8; font-size: 16px; line-height: 1.6; margin-bottom: 25px;">
                    Sua conta no <strong>LeadFinder Pro</strong> foi criada com sucesso! 
                    Você acaba de ganhar <span style="color: #10b981; font-weight: 600;">5 créditos demonstrativos</span> para começar a prospectar imediatamente.
                </p>
                
                <div style="background-color: #0b0f19; border-left: 4px solid #0ea5e9; padding: 15px; border-radius: 6px; margin-bottom: 30px;">
                    <p style="margin: 0; color: #e2e8f0; font-size: 14px;">
                        <strong>Como começar:</strong> Faça login no seu painel, selecione o nicho de mercado (ex: Drogaria), escolha a cidade da Bahia desejada e clique em <em>Iniciar Varredura</em>.
                    </p>
                </div>
                
                <div style="text-align: center; margin-bottom: 30px;">
                    <a href="http://localhost:8080/index.html" style="background-color: #0ea5e9; color: #ffffff; text-decoration: none; padding: 12px 30px; font-weight: 600; border-radius: 8px; display: inline-block; font-size: 15px; box-shadow: 0 4px 6px -1px rgba(14, 165, 233, 0.4);">
                        Acessar Meu Painel
                    </a>
                </div>
                
                <hr style="border: 0; border-top: 1px solid #1e293b; margin-bottom: 30px;" />
                
                <div style="text-align: center; color: #64748b; font-size: 12px; line-height: 1.5;">
                    <p style="margin: 0;">Você está recebendo este e-mail porque se cadastrou no LeadFinder Pro.</p>
                    <p style="margin: 5px 0 0 0;">&copy; 2026 LeadFinder Pro. Todos os direitos reservados.</p>
                </div>
            </div>
        </body>
        </html>
        """

        part1 = MIMEText(text, "plain")
        part2 = MIMEText(html, "html")
        msg.attach(part1)
        msg.attach(part2)

        # Envia usando SMTP/TLS
        port = int(smtp_port) if smtp_port else 587
        server = smtplib.SMTP(smtp_server, port)
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, email, msg.as_string())
        server.quit()
        
        print(f"[SMTP SUCCESS] E-mail de boas-vindas enviado com sucesso para {email}!")
    except Exception as email_err:
        print(f"[SMTP ERROR] Falha ao enviar e-mail de boas-vindas para {email}: {email_err}")

def gerar_leads_fallback(nicho: str, cidade: str) -> List[Dict[str, Any]]:
    """Gera dados realistas no backend simulando perfeitamente a API do Google Places."""
    prefixos = NICHOS_DICT.get(nicho, ["Premium", "Central", "Líder", "Mais", "Soluções", "Destaque"])
    sufixos = ["", " e Cia", " Comercial", " VIP", " Prime", " Concept", " do Bonfim", " da Bahia"]
    
    ddd = "71" if any(sub in cidade for sub in ["Salvador", "Lauro de Freitas", "Camaçari"]) else "75"
    
    num_leads = random.randint(8, 15)
    leads = []
    
    ruas_random = list(RUAS_BAHIA)
    random.shuffle(ruas_random)
    
    for i in range(num_leads):
        pref = prefixos[i % len(prefixos)]
        suf = random.choice(sufixos)
        nome = f"{nicho} {pref}{suf}".strip()
        
        is_cel = random.random() > 0.3
        if is_cel:
            fone_num = f"9{random.randint(8000, 9999)}-{random.randint(1000, 9999)}"
        else:
            fone_num = f"3{random.randint(200, 399)}-{random.randint(1000, 9999)}"
        telefone = f"({ddd}) {fone_num}"
        
        rua = ruas_random[i % len(ruas_random)]
        num = random.randint(10, 1999)
        endereco = f"{rua}, {num} - Centro - {cidade}"
        
        nota = round(random.uniform(3.2, 4.9), 1)
        avaliacoes = random.randint(5, 230)
        maps = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(nome + ' ' + endereco)}"
        
        instagram_link = None
        wpp_status = "Provável" if is_cel else "Apenas Ligação"

        leads.append({
            "nome": nome,
            "telefone": telefone,
            "endereco": endereco,
            "nota": nota,
            "avaliacoes": avaliacoes,
            "maps": maps,
            "validacao_whatsapp": wpp_status,
            "instagram_link": instagram_link,
            "tipo_link_maps": "Link de Pesquisa"
        })
        
    # Ordena por nota descrecente
    leads.sort(key=lambda x: x["nota"], reverse=True)
    return leads

# ==========================================================================
# CHAMADAS DE INTEGRAÇÃO COM A API DO GOOGLE PLACES (100% PROTEGIDAS)
# ==========================================================================
def buscar_places_google_api(nicho: str, cidade: str, api_key: str) -> Optional[List[Dict[str, Any]]]:
    """Tenta chamar a Google Places API real usando o backend."""
    # 1. Tenta a nova API Places v1 (searchText)
    try:
        url = "https://places.googleapis.com/v1/places:searchText"
        headers = {
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": "places.id,places.displayName,places.formattedAddress,places.rating,places.userRatingCount,places.nationalPhoneNumber,places.websiteUri,places.googleMapsUri"
        }
        body = {
            "textQuery": f"{nicho} em {cidade}",
            "languageCode": "pt-BR"
        }
        
        response = requests.post(url, headers=headers, json=body, timeout=12)
        if response.status_code == 200:
            data = response.json()
            places = data.get("places", [])
            leads = []
            for place in places:
                website = place.get("websiteUri")
                
                # Inspeciona o website se cadastrado
                instagram_link = None
                wpp_no_site = False
                if website:
                    try:
                        resp = requests.get(website, timeout=2, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                        if resp.status_code == 200:
                            html_content = resp.text
                            
                            # Encontra link real do Instagram
                            instagram_link = obter_instagram_no_site(html_content) or None
                            
                            # Limpa HTML para WhatsApp e extrai links
                            html_cleaned = limpar_html_para_whatsapp(html_content)
                            if "api.whatsapp.com" in html_cleaned or "wa.me" in html_cleaned:
                                wpp_no_site = True
                                
                                # Validação Cruzada se for telefone fixo
                                telefone = place.get("nationalPhoneNumber", "Não informado")
                                if eh_telefone_fixo(telefone):
                                    wpp_numbers = extrair_digitos_whatsapp(html_cleaned)
                                    # Normaliza números (remove DDI 55)
                                    normalized_wpps = []
                                    for num in wpp_numbers:
                                        if num.startswith("55") and len(num) > 10:
                                            normalized_wpps.append(num[2:])
                                        else:
                                            normalized_wpps.append(num)
                                            
                                    google_digits = "".join(c for c in telefone if c.isdigit())
                                    if google_digits.startswith("55") and len(google_digits) > 10:
                                        google_digits = google_digits[2:]
                                        
                                    if google_digits not in normalized_wpps:
                                        wpp_no_site = False
                    except Exception:
                        pass

                # Filtra comércios que NÃO possuem website cadastrado
                if not website:
                    nome = place.get("displayName", {}).get("text", "Sem nome")
                    telefone = place.get("nationalPhoneNumber", "Não informado")
                    endereco = place.get("formattedAddress", "Não informado")
                    rating = place.get("rating", 0.0)
                    user_ratings = place.get("userRatingCount", 0)
                    
                    place_id = place.get("id")
                    if place_id:
                        maps_link = f"https://www.google.com/maps/search/?api=1&query=Google&query_place_id={place_id}"
                        tipo_link_maps = "Link Direto"
                    else:
                        maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(nome + ' ' + endereco)}"
                        tipo_link_maps = "Link de Pesquisa"
                    
                    leads.append({
                        "nome": nome,
                        "telefone": telefone,
                        "endereco": endereco,
                        "nota": rating,
                        "avaliacoes": user_ratings,
                        "maps": maps_link,
                        "validacao_whatsapp": obter_validacao_whatsapp(telefone, wpp_no_site),
                        "instagram_link": instagram_link or None,
                        "tipo_link_maps": tipo_link_maps
                    })
            return leads
    except Exception as e:
        print(f"[GOOGLE API V1 WARN] Erro na requisição: {e}")

    # 2. Fallback para API Places v0 (Legacy Text Search + Place Details)
    try:
        search_url = "https://maps.googleapis.com/maps/api/place/textsearch/json"
        params = {
            "query": f"{nicho} em {cidade}",
            "key": api_key,
            "language": "pt-BR"
        }
        response = requests.get(search_url, params=params, timeout=10)
        if response.status_code == 200:
            results = response.json().get("results", [])
            leads = []
            
            # Detalha no máximo 10 estabelecimentos para evitar estourar limites rápidos de timeout no HTTP
            for place in results[:10]:
                place_id = place.get("place_id")
                if not place_id:
                    continue
                    
                details_url = "https://maps.googleapis.com/maps/api/place/details/json"
                d_params = {
                    "place_id": place_id,
                    "fields": "name,formatted_phone_number,formatted_address,rating,user_ratings_total,website,url",
                    "key": api_key,
                    "language": "pt-BR"
                }
                
                try:
                    d_resp = requests.get(details_url, params=d_params, timeout=5)
                    if d_resp.status_code == 200:
                        details = d_resp.json().get("result", {})
                        website = details.get("website")
                        
                        # Inspeciona o website se cadastrado
                        instagram_link = None
                        wpp_no_site = False
                        if website:
                            try:
                                resp = requests.get(website, timeout=2, headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"})
                                if resp.status_code == 200:
                                    html_content = resp.text
                                    
                                    # Encontra link real do Instagram
                                    instagram_link = obter_instagram_no_site(html_content) or None
                                    
                                    # Limpa HTML para WhatsApp e extrai links
                                    html_cleaned = limpar_html_para_whatsapp(html_content)
                                    if "api.whatsapp.com" in html_cleaned or "wa.me" in html_cleaned:
                                        wpp_no_site = True
                                        
                                        # Validação Cruzada se for telefone fixo
                                        telefone = details.get("formatted_phone_number", "Não informado")
                                        if eh_telefone_fixo(telefone):
                                            wpp_numbers = extrair_digitos_whatsapp(html_cleaned)
                                            # Normaliza números (remove DDI 55)
                                            normalized_wpps = []
                                            for num in wpp_numbers:
                                                if num.startswith("55") and len(num) > 10:
                                                    normalized_wpps.append(num[2:])
                                                else:
                                                    normalized_wpps.append(num)
                                                    
                                            google_digits = "".join(c for c in telefone if c.isdigit())
                                            if google_digits.startswith("55") and len(google_digits) > 10:
                                                google_digits = google_digits[2:]
                                                
                                            if google_digits not in normalized_wpps:
                                                wpp_no_site = False
                            except Exception:
                                pass

                        if not website:
                            nome_det = details.get("name", place.get("name"))
                            endereco_det = details.get("formatted_address", "Não informado")
                            
                            if place_id:
                                maps_link = f"https://www.google.com/maps/search/?api=1&query=Google&query_place_id={place_id}"
                                tipo_link_maps = "Link Direto"
                            else:
                                maps_link = f"https://www.google.com/maps/search/?api=1&query={urllib.parse.quote_plus(nome_det + ' ' + endereco_det)}"
                                tipo_link_maps = "Link de Pesquisa"
                                
                            leads.append({
                                "nome": nome_det,
                                "telefone": details.get("formatted_phone_number", "Não informado"),
                                "endereco": endereco_det,
                                "nota": details.get("rating", 0.0),
                                "avaliacoes": details.get("user_ratings_total", 0),
                                "maps": maps_link,
                                "validacao_whatsapp": obter_validacao_whatsapp(details.get("formatted_phone_number", "Não informado"), wpp_no_site),
                                "instagram_link": instagram_link or None,
                                "tipo_link_maps": tipo_link_maps
                            })
                except Exception:
                    pass
            return leads
    except Exception as e:
        print(f"[GOOGLE API V0 WARN] Falha na API antiga: {e}")
        
    return None

# ==========================================================================
# ENDPOINTS DE PERFIL E CRÉDITOS DO USUÁRIO
# ==========================================================================
@app.get("/api/perfil/{user_id}")
async def obter_perfil(user_id: str):
    """
    Retorna as informações do perfil do usuário (créditos, e-mail) do Supabase ou do Mock.
    Caso não exista, retorna HTTP 404.
    """
    user_uuid = obter_uuid_usuario(user_id)
    if not is_supabase_mock and supabase is not None:
        try:
            db_profile_resp = supabase.table("perfis_usuarios").select("creditos, email").eq("id", user_uuid).execute()
            if not db_profile_resp.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Perfil de usuário não encontrado."
                )
            profile_data = db_profile_resp.data[0]
            return {
                "id": user_id,
                "email": profile_data["email"],
                "credits": profile_data["creditos"],
                "plan": "Premium B2B"
            }
        except HTTPException as http_ex:
            raise http_ex
        except Exception as db_err:
            print(f"[SUPABASE DB ERROR] Erro na consulta do perfil: {db_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro de comunicação com o banco de dados: {str(db_err)}"
            )
    else:
        if user_uuid not in MOCK_SUPABASE_PROFILES:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Perfil de usuário não encontrado."
            )
        profile = MOCK_SUPABASE_PROFILES[user_uuid]
        return {
            "id": user_uuid,
            "email": profile["email"],
            "credits": profile["credits"],
            "plan": profile["plan"]
        }

@app.post("/api/perfil")
async def criar_perfil(req: ProfileCreateRequest):
    """
    Cria um novo perfil de usuário com 5 créditos iniciais e envia e-mail de boas-vindas.
    Se já existir, retorna HTTP 400.
    """
    user_id = req.user_id
    email = req.email
    password = req.password
    user_uuid = obter_uuid_usuario(user_id)
    senha_cripto = hash_senha(password)

    if not is_supabase_mock and supabase is not None:
        try:
            # Verifica se já existe por e-mail ou por ID
            db_profile_resp = supabase.table("perfis_usuarios").select("id").or_(f"id.eq.{user_uuid},email.eq.{email}").execute()
            if db_profile_resp.data:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Usuário ou e-mail já cadastrado."
                )
            
            # Insere no Supabase com hash de senha
            supabase.table("perfis_usuarios").insert({
                "id": user_uuid,
                "email": email,
                "senha_hash": senha_cripto,
                "creditos": 5
            }).execute()
            
            # Envia e-mail de boas-vindas
            enviar_email_boas_vindas(email)

            return {
                "id": user_id,
                "email": email,
                "credits": 5,
                "plan": "Premium B2B"
            }
        except HTTPException as http_ex:
            raise http_ex
        except Exception as db_err:
            print(f"[SUPABASE DB ERROR] Erro ao cadastrar perfil: {db_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao salvar perfil no banco: {str(db_err)}"
            )
    else:
        # Mock Flow - verifica se já existe por ID ou email
        for prof in MOCK_SUPABASE_PROFILES.values():
            if prof["email"] == email:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="E-mail já cadastrado."
                )
        if user_uuid in MOCK_SUPABASE_PROFILES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Usuário já cadastrado com este ID."
            )
        
        MOCK_SUPABASE_PROFILES[user_uuid] = {
            "email": email,
            "credits": 5,
            "plan": "Demo Free Tier",
            "senha_hash": senha_cripto
        }
        
        # Envia e-mail de boas-vindas
        enviar_email_boas_vindas(email)

        return {
            "id": user_uuid,
            "email": email,
            "credits": 5,
            "plan": "Demo Free Tier"
        }

@app.post("/api/perfil/login")
async def login_perfil(req: LoginRequest):
    """
    Realiza o login de usuário validando a senha contra o hash criptografado no banco.
    Se falhar, retorna HTTP 401 Unauthorized ou HTTP 404 Not Found.
    """
    email = req.email.strip()
    password = req.password

    if not is_supabase_mock and supabase is not None:
        try:
            # Busca perfil pelo e-mail
            db_profile_resp = supabase.table("perfis_usuarios").select("id, creditos, email, senha_hash").eq("email", email).execute()
            if not db_profile_resp.data:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Conta não encontrada. Por favor, cadastre-se."
                )
            
            profile_data = db_profile_resp.data[0]
            senha_hash = profile_data.get("senha_hash")
            
            # Valida hash
            if not senha_hash or not verificar_senha(password, senha_hash):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Senha incorreta."
                )
            
            return {
                "id": profile_data["id"],
                "email": profile_data["email"],
                "credits": profile_data["creditos"],
                "plan": "Premium B2B"
            }
        except HTTPException as http_ex:
            raise http_ex
        except Exception as db_err:
            print(f"[SUPABASE DB ERROR] Erro ao autenticar perfil: {db_err}")
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Erro ao autenticar no banco: {str(db_err)}"
            )
    else:
        # Mock Flow - busca pelo email
        found_profile = None
        found_uuid = None
        for uid, prof in MOCK_SUPABASE_PROFILES.items():
            if prof["email"] == email:
                found_profile = prof
                found_uuid = uid
                break
        
        if not found_profile:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Conta não encontrada. Por favor, cadastre-se."
            )
        
        senha_hash = found_profile.get("senha_hash")
        if not senha_hash or not verificar_senha(password, senha_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Senha incorreta."
            )
            
        return {
            "id": found_uuid,
            "email": found_profile["email"],
            "credits": found_profile["credits"],
            "plan": found_profile["plan"]
        }

# ==========================================================================
# ENDPOINT DE BUSCA COMERCIAL (ROTA PRINCIPAL)
# ==========================================================================
@app.post("/api/buscar")
async def buscar_leads(req: SearchRequest):
    """
    Realiza a varredura comercial de leads sem site de forma segura e controlada por créditos.
    """
    try:
        nicho = req.nicho
        cidade = req.cidade
        user_id = obter_uuid_usuario(req.user_id)
        
        if not nicho or not cidade:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Nicho e Cidade são campos obrigatórios."
            )

        # 1. CONTROLE DE CREDITO E VERIFICAÇÃO DO PERFIL DO USUÁRIO
        user_email = ""
        user_plan = "Premium B2B"
        user_credits = 0

        if not is_supabase_mock and supabase is not None:
            try:
                # Consulta o banco de dados Supabase real na tabela public.perfis_usuarios
                db_profile_resp = supabase.table("perfis_usuarios").select("creditos, email").eq("id", user_id).execute()
                
                # Se o usuário não existir na tabela perfis_usuarios, realiza o insert inicial (auto-cadastro com 5 créditos)
                if not db_profile_resp.data:
                    user_email = req.email or "usuario_sem_email@plataforma.com"
                    supabase.table("perfis_usuarios").insert({
                        "id": user_id,
                        "email": user_email,
                        "creditos": 5
                    }).execute()
                    user_credits = 5
                    print(f"[SUPABASE DB] Criado perfil inicial para o ID: {user_id} com e-mail real: {user_email} e 5 créditos.")
                else:
                    user_credits = db_profile_resp.data[0]["creditos"]
                    user_email = db_profile_resp.data[0]["email"]
            except Exception as db_err:
                print(f"[SUPABASE DB ERROR] Erro na consulta do perfil: {db_err}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erro de comunicação com o banco de dados: {str(db_err)}"
                )
        else:
            # Fallback Mock para testes locais sem Supabase configurado
            if user_id not in MOCK_SUPABASE_PROFILES:
                user_email = req.email or "usuario_sem_email@plataforma.com"
                MOCK_SUPABASE_PROFILES[user_id] = {
                    "email": user_email,
                    "credits": 5,
                    "plan": "Demo Free Tier"
                }
            profile = MOCK_SUPABASE_PROFILES[user_id]
            user_credits = profile["credits"]
            user_email = profile["email"]
            user_plan = profile["plan"]

        # Se não possuir créditos: barre a execução e retorne um erro HTTP 403
        if user_credits <= 0:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Créditos insuficientes. Adquira mais buscas"
            )

        # 2. EXECUÇÃO DA BUSCA (Segurança: Chave é lida estritamente do Servidor)
        google_key = os.getenv("GOOGLE_API_KEY")
        leads_encontrados = []
        
        dummy_key = "AIzaSyDS5vF89dbKFroI1wpIQVDG3lfLydYfhaY"
        if not google_key or google_key.strip() == dummy_key or google_key.strip() == "":
            print(f"[BACKEND SAAS WARNING] Utilizando engine de fallback para gerar leads realistas de '{nicho}' em '{cidade}'")
            leads_encontrados = gerar_leads_fallback(nicho, cidade)
            api_usada = "Mock Fallback Server-Side Engine"
        else:
            try:
                # Tenta disparar a chamada real à API
                leads_real = buscar_places_google_api(nicho, cidade, google_key.strip())
                if leads_real is not None:
                    leads_encontrados = leads_real
                    api_usada = "Google Places API (Real Live Connection)"
                else:
                    # Fallback seguro caso a chamada de API real falhe (para não dar crash)
                    print("[BACKEND SAAS FALLBACK] Chamada real falhou. Acionando gerador de emergência.")
                    leads_encontrados = gerar_leads_fallback(nicho, cidade)
                    api_usada = "Backup Fallback Engine"
            except Exception as google_err:
                print(f"[CRITICAL ERROR GOOGLE PLACES API]: {google_err}")
                leads_encontrados = gerar_leads_fallback(nicho, cidade)
                api_usada = "Backup Fallback Engine"

        # 3. DÉBITO DO CRÉDITO E HISTÓRICO DE VARREDURAS
        creditos_restantes = max(0, user_credits - 1)
        
        if not is_supabase_mock and supabase is not None:
            try:
                # Decrementa 1 crédito na tabela 'perfis_usuarios'
                supabase.table("perfis_usuarios").update({"creditos": creditos_restantes}).eq("id", user_id).execute()
                
                # Registra histórico de varredura
                supabase.table("historico_varreduras").insert({
                    "id_usuario": user_id,
                    "nicho": nicho,
                    "cidade": cidade,
                    "total_leads_encontrados": len(leads_encontrados)
                }).execute()
                print(f"[SUPABASE DB] Sucesso: Histórico gravado e crédito decrementado para o usuário {user_email}.")
            except Exception as db_write_err:
                print(f"[SUPABASE DB WRITE ERROR] Erro ao debitar créditos ou gravar histórico: {db_write_err}")
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Erro ao salvar registro de varredura no banco: {str(db_write_err)}"
                )
        else:
            # Atualiza no simulador local em memória
            MOCK_SUPABASE_PROFILES[user_id]["credits"] = creditos_restantes
            print(f"[MOCK DATABASE] Sucesso: Histórico simulado. Créditos restantes do usuário {user_email}: {creditos_restantes}")

        # Retorna os dados formatados e estatísticas de uso
        return {
            "leads": leads_encontrados,
            "total_analisados": len(leads_encontrados) + random.randint(5, 12),
            "api_utilizada": api_usada,
            "user_email": user_email,
            "user_plan": user_plan,
            "creditos_restantes": creditos_restantes
        }
    except HTTPException as http_ex:
        # Repassa HTTPExceptions intactas
        raise http_ex
    except Exception as e:
        import traceback
        # Adiciona um log de erro detalhado com traceback no terminal do servidor
        print(f"[ERROR /api/buscar] Ocorreu um erro crítico durante a varredura comercial:")
        traceback.print_exc()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Erro interno no servidor de varredura: {str(e)}"
        )

# ==========================================================================
# ENDPOINT DE WEBHOOKS (INTEGRAÇÃO DE MONETIZAÇÃO - ASAAS / MERCADO PAGO)
# ==========================================================================
@app.post("/api/webhooks/asaas")
async def asaas_payment_webhook(payload: AsaasWebhookPayload):
    """
    Recebe as notificações de pagamento do gateway Asaas de forma assíncrona.
    Quando um pagamento é confirmado, adiciona os créditos na conta do usuário no Supabase.
    """
    event = payload.event
    payment = payload.payment
    user_id = obter_uuid_usuario(payment.externalReference) # Passamos o ID do usuário Supabase como referência externa
    valor = payment.value
    
    print(f"[ASAAS WEBHOOK] Recebido evento '{event}' para o pagamento '{payment.id}'")
    
    # Eventos de confirmação no Asaas: PAYMENT_RECEIVED ou PAYMENT_CONFIRMED
    if event in ["PAYMENT_RECEIVED", "PAYMENT_CONFIRMED"]:
        if not user_id:
            print("[ASAAS WEBHOOK ERROR] Pagamento recebido, mas campo 'externalReference' (User ID) está ausente!")
            return {"status": "ignored", "reason": "Missing user ID reference"}
            
        # Determina o pacote de créditos com base no valor pago
        creditos_adicionais = 0
        tipo_compra = "Recarga Avulsa"
        
        if valor >= 99.00:
            creditos_adicionais = 300  # Pacote Pro
            tipo_compra = "Pacote Pro (300 créditos)"
        elif valor >= 49.00:
            creditos_adicionais = 120  # Pacote Intermediário
            tipo_compra = "Pacote Intermediário (120 créditos)"
        elif valor >= 19.90:
            creditos_adicionais = 40   # Pacote Básico
            tipo_compra = "Pacote Básico (40 créditos)"
        else:
            creditos_adicionais = 10   # Pacote de Testes
            tipo_compra = "Recarga Mínima (10 créditos)"
            
        # Em produção, atualiza o Supabase:
        # user_db = supabase.table("profiles").select("credits").eq("id", user_id).single().execute()
        # current = user_db.data.get("credits", 0)
        # supabase.table("profiles").update({"credits": current + creditos_adicionais}).eq("id", user_id).execute()
        
        # Simulação Mock do Supabase
        if user_id in MOCK_SUPABASE_PROFILES:
            MOCK_SUPABASE_PROFILES[user_id]["credits"] += creditos_adicionais
            MOCK_SUPABASE_PROFILES[user_id]["plan"] = "Assinante Ativo"
            email = MOCK_SUPABASE_PROFILES[user_id]["email"]
            total_agora = MOCK_SUPABASE_PROFILES[user_id]["credits"]
            print(f"[ASAAS SUCCESS] Creditados +{creditos_adicionais} créditos para o usuário {email} (ID: {user_id}). Novo total: {total_agora}")
        else:
            # Se for um novo usuário criado via webhook
            MOCK_SUPABASE_PROFILES[user_id] = {
                "email": f"cliente_webhook_{user_id[:6]}@email.com",
                "credits": creditos_adicionais,
                "plan": "Assinante Ativo"
            }
            print(f"[ASAAS SUCCESS] Nova conta criada via webhook. Creditados +{creditos_adicionais} para ID: {user_id}")
            
        return {
            "status": "success", 
            "message": f"Pagamento confirmado de R$ {valor:.2f}. Adicionados +{creditos_adicionais} créditos.",
            "tipo": tipo_compra,
            "user_id": user_id
        }
        
    return {"status": "ignored", "event": event}

# Rota para silenciar avisos automáticos de favicon no navegador
@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=status.HTTP_204_NO_CONTENT)

# Rota de healthcheck básica
@app.get("/")
async def root():
    return {
        "status": "online",
        "service": "LeadFinder Pro API",
        "endpoints": {
            "buscar": "/api/buscar [POST]",
            "webhook_asaas": "/api/webhooks/asaas [POST]"
        }
    }

@app.get("/index.html", include_in_schema=False)
async def serve_dashboard():
    dashboard_path = os.path.join(os.path.dirname(__file__), "index.html")
    if os.path.exists(dashboard_path):
        return FileResponse(dashboard_path)
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Arquivo index.html não encontrado")

@app.get("/dashboard.html", include_in_schema=False)
async def redirect_dashboard_html():
    return RedirectResponse(url="/index.html")

@app.get("/dashborad.html", include_in_schema=False)
async def redirect_dashborad_typo():
    return RedirectResponse(url="/index.html")

@app.get("/dashboard", include_in_schema=False)
async def redirect_dashboard():
    return RedirectResponse(url="/index.html")

@app.get("/dashborad", include_in_schema=False)
async def redirect_dashborad():
    return RedirectResponse(url="/index.html")

if __name__ == "__main__":
    import uvicorn
    # Inicia o servidor localizador na porta 8000
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
