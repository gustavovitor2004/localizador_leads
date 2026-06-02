# 🔍 Localizador de Leads Sem Site (Google Places)

Um script Python premium e robusto, projetado para desenvolvedores e agências de web design encontrarem comércios locais que **não possuem site cadastrado no Google**. Perfeito para prospecção ativa de serviços de desenvolvimento web e SEO local.

---

## ✨ Recursos do Script

- **🌐 Arquitetura de API Dupla (Inteligente & Econômica):**
  - **API Google Places v1 (Nova):** Usada por padrão. Obtém dados avançados como Telefone e Website em uma única consulta rápida e barata ($0.04 por consulta de 20 lugares em vez de $0.37).
  - **API Google Places Legacy (v0):** Fallback automático caso a chave de API não tenha o novo endpoint habilitado. Realiza busca por texto e consulta detalhada de cada local de forma transparente.
- **🛡️ Tratamento de Erros Robusto:** Proteção total contra falhas de conexão, timeouts de API, chaves inválidas ou cotas excedidas.
- **📊 Exportação Premium para Excel:**
  - Gera uma planilha Excel (`leads_sem_site.xlsx`) com visual profissional corporativo (cabeçalho azul escuro bold, linhas de grade ativas, colunas autoajustáveis e alinhamentos adequados).
  - **Fallback para CSV:** Se a biblioteca de Excel (`openpyxl`) não estiver disponível ou falhar, salva automaticamente um arquivo de segurança em CSV (`leads_sem_site.csv`) para evitar qualquer perda de dados.
- **⚡ Console Interativo:** Interface CLI elegante com cores ANSI, banner estilizado, animação de progresso e exibição em tabela dos resultados diretamente no terminal.

---

## 🛠️ Requisitos e Instalação

### 1. Python 3
O script requer o Python 3 instalado. *(Nota: O assistente iniciou a instalação silenciosa do Python 3.12 no seu Windows via `winget` se não estivesse disponível).*

### 2. Instalação das Dependências
Para instalar as bibliotecas necessárias, abra o seu terminal na pasta do projeto e execute:

```bash
pip install requests pandas openpyxl python-dotenv
```

---

## 🔑 Como Obter e Configurar sua API Key do Google Cloud

Para conectar-se ao Google Places, você precisará de uma chave de API válida com faturamento ativo no Google Cloud Console.

### Passo a Passo para Obter a Chave:
1. Acesse o [Google Cloud Console](https://console.cloud.google.com/).
2. Crie um novo projeto (ex: "Localizador de Leads") ou use um existente.
3. Acesse o menu lateral ➔ **APIs e Serviços** ➔ **Biblioteca**.
4. Pesquise e **Ative** as seguintes APIs:
   - **Places API** (API padrão de locais)
   - **Places API (New)** (API recomendada de locais v1)
5. Acesse o menu lateral ➔ **APIs e Serviços** ➔ **Credenciais**.
6. Clique em **+ Criar Credenciais** ➔ **Chave de API**.
7. Copie a chave gerada. *(Dica: É altamente recomendável restringir sua chave para ser usada apenas com a API Places para segurança).*

### Como Inserir a Chave no Script:
O script é flexível e busca a chave em 3 locais, nesta ordem de prioridade:
1. **Arquivo `.env` (Recomendado):** Crie um arquivo chamado `.env` na raiz do projeto (ou duplique o `.env.example`) e adicione sua chave nele:
   ```env
   GOOGLE_API_KEY=sua_chave_aqui
   ```
2. **Variável de Ambiente:** Se preferir, configure uma variável de ambiente chamada `GOOGLE_API_KEY` no seu terminal.
3. **Entrada Dinâmica:** Se nenhuma chave for encontrada, o script solicitará que você cole a chave diretamente no terminal ao iniciar a execução, com a opção de salvá-la em um arquivo `.env` automaticamente para buscas futuras.

---

## 🚀 Como Executar o Script

Você pode rodar o script de duas maneiras:

### Opção A: Execução Interativa (Recomendado)
Execute o script sem argumentos. Ele abrirá um menu interativo elegante perguntando o nicho e a cidade que deseja prospectar:

```bash
python localizador_leads.py
```

### Opção B: Execução via Linha de Comando (Modo Direto)
Passe o nicho e a cidade diretamente como argumentos de comando (entre aspas):

```bash
python localizador_leads.py "barbearia" "Feira de Santana - BA"
```

---

## 📄 Estrutura dos Dados Exportados

Para cada estabelecimento sem site encontrado, a planilha exportada conterá:
- **Nome:** Nome do estabelecimento comercial.
- **Telefone:** Telefone comercial formatado para contato de prospecção.
- **Endereço:** Endereço completo para geolocalização ou envio de propostas físicas.
- **Avaliação (Nota):** Nota média de avaliação (de 0 a 5.0).
- **Avaliações (Total):** Quantidade de pessoas que avaliaram o local (indica o nível de atividade/movimento do comércio).
