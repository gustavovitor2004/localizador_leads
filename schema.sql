-- Script SQL para o Editor de Consultas (SQL Editor) do Supabase

-- Habilita a extensão uuid-ossp se ela não estiver habilitada
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- 1. Criação da tabela de perfis de usuários (vinculada ao auth.users do Supabase Auth)
CREATE TABLE IF NOT EXISTS public.perfis_usuarios (
    id UUID PRIMARY KEY,                                     -- ID do usuário (mapeado de auth.users.id)
    email TEXT NOT NULL UNIQUE,                              -- Endereço de e-mail do usuário (único)
    senha_hash TEXT,                                         -- Hash seguro da senha (criptografia pbkdf2)
    creditos INTEGER NOT NULL DEFAULT 5,                     -- Saldo de créditos de varreduras (padrão 5)
    data_cadastro TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL
);

-- Migração para adicionar coluna de senha_hash caso a tabela já exista
ALTER TABLE public.perfis_usuarios ADD COLUMN IF NOT EXISTS senha_hash TEXT;
ALTER TABLE public.perfis_usuarios ADD COLUMN IF NOT EXISTS email TEXT;
-- Garante restrição de unicidade no email se possível (caso falhe por já existir, é ignorado)
ALTER TABLE public.perfis_usuarios ADD CONSTRAINT uq_email_perfis UNIQUE (email);

-- 2. Criação da tabela de histórico de varreduras realizadas pelos usuários
CREATE TABLE IF NOT EXISTS public.historico_varreduras (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),            -- ID único do registro da busca
    id_usuario UUID NOT NULL,                                -- ID do usuário que realizou a busca (chave estrangeira)
    nicho TEXT NOT NULL,                                     -- Nicho/comércio pesquisado (ex: Barbearia)
    cidade TEXT NOT NULL,                                    -- Cidade/Bahia pesquisada (ex: Salvador - BA)
    data_busca TIMESTAMP WITH TIME ZONE DEFAULT now() NOT NULL, -- Data e hora do processamento da busca
    total_leads_encontrados INTEGER NOT NULL DEFAULT 0,      -- Quantidade de leads qualificados encontrados
    CONSTRAINT fk_historico_usuario FOREIGN KEY (id_usuario) 
        REFERENCES public.perfis_usuarios(id) 
        ON DELETE CASCADE
);

-- Habilita segurança de linha (RLS) nas tabelas se desejar controle extra, 
-- ou configure as políticas adequadas para acesso da service_role/anon.
ALTER TABLE public.perfis_usuarios ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.historico_varreduras ENABLE ROW LEVEL SECURITY;

-- Políticas de acesso básicas para usuários poderem ver seus próprios dados
CREATE POLICY "Usuários podem visualizar seu próprio perfil" 
    ON public.perfis_usuarios 
    FOR SELECT 
    USING (auth.uid() = id);

CREATE POLICY "Usuários podem visualizar seu próprio histórico" 
    ON public.historico_varreduras 
    FOR SELECT 
    USING (auth.uid() = id_usuario);
