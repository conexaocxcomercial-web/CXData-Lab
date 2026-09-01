# core.cx

Plataforma interna da **conexão.cx** — RH e recrutamento. Reúne quadros de
trabalho, CRM comercial, controle de tempo e painéis de indicadores.

## Stack

- **Backend:** Flask — `app.py` (~5.900 linhas) e `acessos_v2.py`
- **Banco:** Supabase (PostgreSQL), acessado via `supabase-py`
- **Deploy:** Vercel, branch `main`
- **Frontend:** templates Jinja2, HTML/CSS/JS puro

**Não há processo de build.** Cada tela é um `.html` autocontido, com CSS e
JS embutidos. É intencional: deploy é copiar arquivo. Não introduza
bundler, framework ou etapa de compilação sem combinar antes.

## Convenções

- **Português** em nomes, comentários e mensagens de interface
- Comentários explicam **por que**, não o que — o código já diz o que faz
- Sem dependências novas sem combinar: o `requirements.txt` é curto de
  propósito

## Antes de entregar qualquer alteração

Ler o código não basta. Vários bugs só apareceram executando:

```bash
# sintaxe
python3 -c "import ast,io; ast.parse(io.open('app.py',encoding='utf-8',newline='').read())"

# JS de cada bloco <script> da página renderizada
node --check bloco.js

# a página funciona? (jsdom: carregar, clicar, capturar console.error)
```

O último passo é o que pega os erros que importam.

---

## Armadilhas conhecidas

Verifique estas antes de suspeitar de outra coisa. Cada uma já custou
várias horas.

**PostgREST corta em 1.000 linhas, em silêncio.** Sem erro, sem aviso: a
lista vem menor. Use `_paginar()` para qualquer tabela que possa crescer.
Isso já produziu conversão de 162% no funil comercial.

**RLS ligado sem política nenhuma = negar tudo.** Aconteceu com
`projeto_movimentos` e com o bucket `contratos`. O sintoma é gravação que
falha em silêncio dentro de um `try/except`.

**Cada tela tem seus próprios helpers.** `crm.html` usa `escH()`,
`comercial.html` usa `esc()` e `num()`, `dashboard.html` usa `n()`. Copiar
código entre telas quebra com "X is not defined" — e derruba a função
inteira sem mensagem na tela.

**Importação de CSV grava a palavra "null"** onde a célula está vazia.
Quatro letras que o JavaScript considera texto preenchido.

**A coluna `usuarios.senha` é NOT NULL.** Gravar `None` derruba o update
inteiro.

**`data_inicio` não significa "começou a trabalhar"** — é gravado na
primeira mudança de status qualquer. Para o ciclo, use
`data_saida_backlog`.

---

## Regras de negócio

Já foram decididas. Não refazer sem conversar.

### Tempo nos quadros de trabalho

- **Lead time** = entrada no Backlog → Finalizado
- **Cycle time** = saída do Backlog → fim do ciclo
- **Pausado congela os dois.** Na conexão.cx a pausa parte sempre do
  cliente, então não é justo cobrar do time. Os dias parados viram
  `tempo_parado_segundos`, medidos à parte.
- **Em R&S o ciclo termina em "Entrevista com o cliente"**, não em
  Finalizado: o serviço é entregar candidatos, e o que vem depois é tempo
  do cliente. Configurado em `FIM_DO_CICLO`, por área.

### CRM

Quatro funis: `qualificacao`, `fechamento`, `relacionamento`, `nutricao`.

**Distinção que muda todos os números:**
- `qualificacao/Ganho` = lead qualificado, passou para o closer
- `fechamento/Ganho` = contrato assinado

Somar os dois infla a receita com leads que nem receberam proposta.

**Caminho obrigatório** (`CAMINHO_OBRIGATORIO`):
- qualificacao: Prospecção → Contato → Ganho
- fechamento: Agendamento → Proposta → Negociação → Ganho

Quem pula etapa tem as passagens criadas automaticamente, marcadas com
`objecao = 'etapa preenchida automaticamente'`. Follow up 1..4 são
tentativas, não etapas obrigatórias.

### Contagem nos painéis

**Etapa terminal conta pelo estado atual; etapa de passagem, pela
trilha.** Ganho e Perdido são situação, não passagem — e situação se
desfaz. Passar por Contato ou Proposta é fato consumado.

**A cobertura anda junto do número.** Quando uma média cobre parte da
base, a tela mostra "212 de 374 entregas". Média lida como se fosse o
todo leva à decisão errada.

**Mediana, não média,** em tempo de ciclo. Um lead parado há meses
distorce a média e faz o time desconfiar do número.

### Acessos

Nível **por quadro** (`usuarios.acessos`, jsonb): ausente = não vê;
`proprio` = vê o quadro, detalhes só dos próprios cards; `tudo` = vê e
edita o trabalho de todos ali.

Mais uma lista de **telas** (`usuarios.areas`) em liga/desliga.

**Regra:** quem enxerga o card, edita o card. Não existe permissão
separada para editar — o que limita é o alcance.

---

## Pendências

**Segurança — antes de qualquer feature nova**
- `FLASK_SECRET_KEY` com valor padrão no código, em repositório público.
  Permite forjar cookie de administrador e contorna todo o controle de
  acesso.
- Chave anon do Supabase também embutida.
- Correção: repositório privado → rotacionar chaves → definir
  `FLASK_SECRET_KEY`, `SUPABASE_URL` e `SUPABASE_SERVICE_KEY` como
  variáveis de ambiente na Vercel → remover os padrões do código.

**Menores**
- Produto `Palestra` (1 lead) fora da lista oficial
- Tabelas `staging_leads` e `staging_historico` podem ser apagadas
- Painel operacional pronto, nunca revisado com dados reais
- `projetos.html` (238 KB) e `crm.html` (167 KB) são grandes demais;
  separar CSS e JS reduziria custo e evitaria a divergência de helpers

---

## Estado dos dados

**CRM:** 1.493 leads importados do sistema anterior, desde 29/06/2026,
com 3.914 movimentos. Entraram sem marca de importação, mas com
`id_origem` gravado — é o que liga cada movimento ao lead e permite
desfazer em bloco (`where id_origem is not null`).

**Quadros:** 486 projetos. `projeto_movimentos` e `historico_colunas`
guardam a mesma trilha em paralelo — a segunda sobreviveu a um período em
que RLS bloqueava a primeira.

A migração do CRM antigo ainda está em uso: exportar dois CSV, subir em
`staging_leads` e `staging_historico`, rodar a importação.
