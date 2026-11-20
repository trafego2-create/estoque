-- Brabo Estoque — estrutura no banco comercial (xmkamph…), schema próprio `estoque`.
-- Padrão dos outros sistemas internos do Operacional (schemas radar, virtua, encurtador):
-- schema separado = NÃO fica exposto na API pública do Supabase (chave anon não alcança).
-- Rodar uma vez. É aditivo: não toca em nada que já existe.

create schema if not exists estoque authorization postgres;

-- atualiza `atualizado_em` em qualquer UPDATE
create or replace function estoque.tocar() returns trigger language plpgsql as $$
begin
  new.atualizado_em := now();
  return new;
end $$;

-- ───────────────────────── quem usa o site (login) ─────────────────────────
create table if not exists estoque.usuarios (
  id          bigserial primary key,
  email       text not null,
  nome        text not null,
  senha_hash  text not null,
  papel       text not null default 'operador' check (papel in ('operador','supervisor')),
  ativo       boolean not null default true,
  criado_em   timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);
create unique index if not exists usuarios_email_uk on estoque.usuarios (lower(btrim(email)));
drop trigger if exists usuarios_tocar on estoque.usuarios;
create trigger usuarios_tocar before update on estoque.usuarios
  for each row execute function estoque.tocar();

-- ──────────────────── colaboradores (com quem fica o item) ────────────────────
create table if not exists estoque.colaboradores (
  id          bigserial primary key,
  nome        text not null,
  setor       text,
  cargo       text,
  email       text,
  ativo       boolean not null default true,
  observacao  text,
  criado_em   timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);
-- evita cadastrar a mesma pessoa duas vezes durante a coleta
create unique index if not exists colaboradores_nome_uk on estoque.colaboradores (lower(btrim(nome)));
create index if not exists colaboradores_setor_ix on estoque.colaboradores (setor);
drop trigger if exists colaboradores_tocar on estoque.colaboradores;
create trigger colaboradores_tocar before update on estoque.colaboradores
  for each row execute function estoque.tocar();

-- ───────────────────────────── equipamentos ─────────────────────────────
create table if not exists estoque.equipamentos (
  id          bigserial primary key,
  patrimonio  text,                                   -- código de patrimônio (pode faltar na hora)
  -- normalizado só para a unicidade: "AS-001" e "as-001 " são o mesmo código
  patrimonio_norm text generated always as (nullif(upper(btrim(patrimonio)), '')) stored,
  tipo        text not null,                           -- Notebook, Monitor, Headset…
  descricao   text,                                    -- "Dell Latitude 3420"
  marca       text,
  modelo      text,
  serie       text,                                    -- número de série
  setor       text,                                    -- setor onde o item está
  localizacao text,                                    -- sala, mesa, armário
  condicao    text not null default 'bom'
              check (condicao in ('novo','bom','regular','ruim','defeito')),
  status      text not null default 'em_estoque'
              check (status in ('em_estoque','com_colaborador','manutencao','emprestado','baixado')),
  colaborador_id bigint references estoque.colaboradores(id) on delete set null,
  valor       numeric(12,2),
  observacao  text,
  criado_em   timestamptz not null default now(),
  criado_por  text,
  atualizado_em timestamptz not null default now(),
  atualizado_por text,
  -- "com colaborador" exige dizer com quem; o resto não pode ficar com dono
  constraint equipamentos_dono_coerente check (
    (status = 'com_colaborador' and colaborador_id is not null)
    or (status <> 'com_colaborador' and colaborador_id is null)
  )
);
create unique index if not exists equipamentos_patrimonio_uk
  on estoque.equipamentos (patrimonio_norm) where patrimonio_norm is not null;
create index if not exists equipamentos_status_ix      on estoque.equipamentos (status);
create index if not exists equipamentos_colaborador_ix on estoque.equipamentos (colaborador_id);
create index if not exists equipamentos_setor_ix       on estoque.equipamentos (setor);
drop trigger if exists equipamentos_tocar on estoque.equipamentos;
create trigger equipamentos_tocar before update on estoque.equipamentos
  for each row execute function estoque.tocar();

-- ──────────────── histórico (quem entregou o que, pra quem, quando) ────────────────
create table if not exists estoque.movimentacoes (
  id          bigserial primary key,
  equipamento_id bigint not null references estoque.equipamentos(id) on delete cascade,
  acao        text not null check (acao in
              ('cadastro','edicao','entrega','devolucao','transferencia','manutencao','retorno','baixa','exclusao')),
  de_colaborador_id   bigint references estoque.colaboradores(id) on delete set null,
  para_colaborador_id bigint references estoque.colaboradores(id) on delete set null,
  de_status   text,
  para_status text,
  setor       text,
  observacao  text,
  usuario     text,                                    -- e-mail de quem registrou no site
  criado_em   timestamptz not null default now()
);
create index if not exists movimentacoes_equip_ix on estoque.movimentacoes (equipamento_id, criado_em desc);
create index if not exists movimentacoes_data_ix  on estoque.movimentacoes (criado_em desc);

-- ─────────── reenvio seguro (celular sem sinal) ───────────
-- O app guarda o que você registrou offline e reenvia depois. Estes dois campos são o
-- "número do bilhete" gerado no celular: se o mesmo bilhete chegar duas vezes, o banco
-- recusa a cópia em vez de criar item/movimento duplicado.
alter table estoque.equipamentos  add column if not exists origem_id text;
alter table estoque.movimentacoes add column if not exists origem_id text;
create unique index if not exists equipamentos_origem_uk  on estoque.equipamentos  (origem_id) where origem_id is not null;
create unique index if not exists movimentacoes_origem_uk on estoque.movimentacoes (origem_id) where origem_id is not null;
