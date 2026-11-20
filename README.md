# Brabo Estoque

Controle dos equipamentos internos da empresa, feito para usar **no celular, andando pela
empresa**. Responde duas perguntas:

- **o que a empresa tem** (aba Estoque);
- **com quem está cada coisa** (aba Pessoas).

Campos principais: **setor**, **equipamento** (tipo + descrição) e **código de patrimônio**,
mais marca, modelo, nº de série, local, condição, valor e observação.

## Como usar no celular

1. Abra o endereço do site e entre com e-mail e senha.
2. Menu do navegador → **Adicionar à tela inicial**: vira um ícone e abre sem barra do navegador.
3. Aba **Registrar**: preencha e toque em **Salvar e cadastrar o próximo**. O setor e a pessoa
   continuam preenchidos, então dá para varrer uma sala inteira sem redigitar nada.
4. Sem sinal? O registro vai para uma fila no aparelho e sobe sozinho quando a rede volta
   (aparece "N na fila" no topo). Cada registro leva um identificador próprio, então reenviar
   nunca cria item duplicado.
5. Para consultar offline, a última leitura fica guardada no aparelho.

Movimentações disponíveis no item: entregar, devolver, passar para outra pessoa, mandar para
manutenção, registrar o retorno e dar baixa. Toda mudança fica no histórico (quem fez e quando).

A planilha completa sai em **⋯ → Baixar planilha (CSV)** (abre no Excel, separador `;`).

## Onde roda

- **Site:** EasyPanel novo (`qacfzn`), projeto `automacoes`, serviço `brabo-estoque`.
- **Banco:** Postgres do Supabase **comercial** (`xmkamph…`), schema **`estoque`**.
  O app entra com o usuário de banco **`estoque_app`**, que só alcança esse schema — não vê
  vendas nem nenhuma outra tabela da empresa. O schema também não fica exposto na API pública
  do Supabase (mesma escolha dos schemas `radar`, `virtua` e `encurtador`).
- **Tabelas:** `estoque.usuarios`, `estoque.colaboradores`, `estoque.equipamentos`,
  `estoque.movimentacoes` (ver `sql/001_estoque.sql`).

## Variáveis de ambiente

| Variável | Para que serve |
| --- | --- |
| `DATABASE_URL` | Postgres do Supabase comercial, usuário `estoque_app`, **porta 6543** (pooler em modo transação; a 5432 tem teto de 15 conexões para toda a empresa) |
| `SESSION_SECRET` | assina o cookie de login; trocar desloga todo mundo |
| `COOKIE_SECURE` | `1` em produção (https), `0` no PC |
| `SESSAO_HORAS` | quanto tempo o login dura (padrão 720 h = 30 dias, porque é celular em uso) |

## Quem pode entrar

Só quem tiver usuário criado:

```bash
python scripts/criar_usuario.py "Nome da Pessoa" email@aprovasim.com            # operador
python scripts/criar_usuario.py "Nome da Pessoa" email@aprovasim.com supervisor # pode excluir
```

A senha é sorteada e aparece na tela uma vez; cada um troca a sua no site
(**⋯ → Trocar minha senha**). Operador faz todo o resto: cadastrar, editar e movimentar.

## Rodar no PC

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
# .env na raiz com DATABASE_URL, SESSION_SECRET e COOKIE_SECURE=0
.venv/Scripts/python.exe -m uvicorn app.main:app --port 8111
```

## Testes

```bash
.venv/Scripts/python.exe -m pytest -q
```

Os testes usam um banco de mentira e têm uma **trava que faz o teste falhar se tentar falar
com o Supabase de verdade** (um teste sem isolamento já trocou a senha de um usuário real
durante o desenvolvimento).

## Organização do código

| Arquivo | O que faz |
| --- | --- |
| `app/main.py` | rotas HTTP, login e planilha |
| `app/dados.py` | tudo que fala com o banco |
| `app/regras.py` | regras sem banco (validação, ações) — é onde os testes batem mais |
| `app/db.py` | pool de conexões (pequeno, reciclado, com nova tentativa) |
| `app/security.py` | senha (scrypt) e cookie assinado — mesmo padrão do Radar e do Brabo Send |
| `public/` | a tela (HTML + JS puro), ícones, manifest e service worker |
