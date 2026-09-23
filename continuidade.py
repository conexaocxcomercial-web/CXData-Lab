# -*- coding: utf-8 -*-
"""
core.cx · Continuidade da conta
===============================

Rotas de LEITURA que alimentam os painéis dos cards expandidos:

    GET /api/projetos/<id>/origem      Origem comercial (card de produto ou interno)
    GET /api/projetos/<id>/contrato    Link temporário do contrato, pelo card
    GET /api/projetos/<id>/destinos    Quem recebe cobrança e relacionamento ao finalizar
    GET /api/leads/<id>/conta          Conta do cliente vista do lead (CRM e Relacionamento)
    GET /api/clientes/por-cnpj         Trava: este CNPJ já é cliente?

POR QUE UM MÓDULO À PARTE
-------------------------
As gravações (fechamento, abertura de quadros, finalização) vivem no
app.py porque estão entrelaçadas com o motor de fluxo. As leituras não
têm essa dependência e, juntas, contam a história de uma conta de ponta
a ponta -- ler o arquivo inteiro é ler a jornada.

PRINCÍPIO
---------
Cadastro é vínculo vivo: contato, telefone, e-mail, CNPJ vêm do lead e do
cliente na hora de responder. Acordo e entrega são foto: vêm do jsonb
gravado no momento em que aconteceram. Histórico é trilha: vem das
tabelas de movimentos que já existem, sem duplicar nada.

CHAVE DA CONTA
--------------
O que liga tudo é o cliente. Quando `cliente_id` está presente, é ele;
quando não está (cadastro antigo), o CNPJ pelos dígitos faz o papel.
"""

from datetime import datetime, timezone

from flask import Blueprint, jsonify, request, session

continuidade_bp = Blueprint('continuidade', __name__)

_ctx = {}


def configurar(**deps):
    """Recebe do app.py o que este módulo precisa. Injetado, não importado,
    para não criar import circular e para o módulo ser testável com dublês."""
    _ctx.update(deps)


def _c(nome):
    return _ctx[nome]


# ============================================================================
# leitura básica
# ============================================================================

def _um(tabela, colunas, chave, valor):
    try:
        r = _c('supabase').table(tabela).select(colunas).eq(chave, valor).limit(1).execute()
        return (r.data or [None])[0]
    except Exception as e:
        print(f"Aviso: {tabela} indisponivel:", e)
        return None


def _lista(tabela, colunas, filtro, limite=500):
    try:
        q = _c('supabase').table(tabela).select(colunas)
        q = filtro(q)
        return q.limit(limite).execute().data or []
    except Exception as e:
        print(f"Aviso: {tabela} indisponivel:", e)
        return []


def _projeto_visivel(projeto):
    """Quem não vê o card não vê a origem dele."""
    return bool(_c('filtrar_projetos_permitidos')([projeto]))


def _quadro_da_area(area):
    for chave, a in _c('QUADRO_AREA').items():
        if a == area:
            return chave
    return None


def _eh_produto(area):
    chave = _quadro_da_area(area)
    return chave in _c('QUADROS_PRODUTO') if chave else False


def _vazio(d):
    return not any(v not in (None, '', [], {}) for v in (d or {}).values())


# ============================================================================
# a conta: tudo de um cliente, por cliente_id ou por CNPJ
# ============================================================================

def _leads_da_conta(cliente_id, cnpj):
    """Leads ativos da mesma conta. Por cliente_id quando há; por CNPJ
    (dígitos) para os cadastros anteriores ao vínculo."""
    dig = _c('so_digitos')(cnpj)
    colunas = ("id, empresa, contato, funil, coluna, produto, responsavel, valor_estimado, "
               "criado_em, movido_em, cliente_id, lead_pai_id, cnpj, contrato_arquivo, entrega")
    saida, vistos = [], set()
    if cliente_id:
        for l in _lista("leads", colunas,
                        lambda q: q.eq("cliente_id", cliente_id).is_("excluido_em", "null")):
            saida.append(l); vistos.add(str(l["id"]))
    if len(dig) == 14:
        # Sem filtro por expressão no PostgREST: traz leads com CNPJ e
        # compara os dígitos aqui. O índice da migração cobre o filtro.
        for l in _c('_paginar')("leads", colunas,
                                lambda q: q.is_("excluido_em", "null").not_.is_("cnpj", "null")):
            if str(l["id"]) in vistos:
                continue
            if _c('so_digitos')(l.get("cnpj")) == dig:
                saida.append(l); vistos.add(str(l["id"]))
    return saida


def _projetos_da_conta(cliente_id, lead_ids):
    colunas = ("id, nome_projeto, area, subquadro, status, responsavel, criado_em, "
               "data_inicio, data_conclusao, prazo_data, valor, lote_id, lote_pos, lote_total, "
               "origem_lead_id, cliente_id, passagem, aguardando_responsavel")
    saida, vistos = [], set()
    if cliente_id:
        for p in _lista("projetos", colunas,
                        lambda q: q.eq("cliente_id", cliente_id).is_("excluido_em", "null"), 1000):
            saida.append(p); vistos.add(str(p["id"]))
    ids = [str(i) for i in lead_ids if i]
    if ids:
        for p in _lista("projetos", colunas,
                        lambda q: q.in_("origem_lead_id", ids).is_("excluido_em", "null"), 1000):
            if str(p["id"]) not in vistos:
                saida.append(p); vistos.add(str(p["id"]))
    return saida


def _resumo_conta(cliente_id, cnpj, pode_valor):
    """Contratos, entregas, andamento e quadros tocados de uma conta."""
    leads = _leads_da_conta(cliente_id, cnpj)
    projetos = _projetos_da_conta(cliente_id, [l["id"] for l in leads])
    projetos = _c('filtrar_projetos_permitidos')(projetos)
    encerrados = _c('STATUS_ENCERRADOS')

    contratos = []
    for l in leads:
        # Contrato = lead ganho. Lead de relacionamento ainda aberto não é
        # contrato; vira quando fechar de novo (e aí é outro lead).
        if l.get("coluna") == "Ganho":
            passagem = next((p.get("passagem") or {} for p in projetos
                             if str(p.get("origem_lead_id")) == str(l["id"]) and p.get("passagem")), {})
            contratos.append({
                "lead_id": l["id"],
                "data": (passagem.get("fechado_em") or l.get("movido_em") or l.get("criado_em")),
                "produto": l.get("produto") or passagem.get("produto"),
                "valor": (l.get("valor_estimado") or passagem.get("valor_contrato")) if pode_valor else None,
                "closer": passagem.get("closer") or l.get("responsavel"),
                "resumo": passagem.get("resumo"),
                "contrato": bool((l.get("contrato_arquivo") or {}).get("caminho")),
            })
    contratos.sort(key=lambda c: str(c["data"] or ''), reverse=True)

    entregas, andamento, quadros = [], [], {}
    for p in projetos:
        chave = _quadro_da_area(p.get("area"))
        q = quadros.setdefault(chave or p.get("area"), {
            "quadro": chave, "area": p.get("area"), "produto": _eh_produto(p.get("area")),
            "total": 0, "finalizados": 0, "em_andamento": 0, "sem_dono": 0,
            "responsaveis": set(), "cards": [],
        })
        q["total"] += 1
        if p.get("responsavel"):
            q["responsaveis"].add(p["responsavel"])
        if p.get("aguardando_responsavel"):
            q["sem_dono"] += 1
        ent = (p.get("passagem") or {}).get("entrega") or {}
        item = {
            "id": p["id"], "nome": p.get("nome_projeto"), "area": p.get("area"),
            "quadro": chave, "status": p.get("status"), "responsavel": p.get("responsavel"),
            "concluido_em": p.get("data_conclusao"), "prazo": p.get("prazo_data"),
            "lote": (f"{p['lote_pos']}/{p['lote_total']}" if p.get("lote_total") else None),
            "satisfacao": ent.get("satisfacao"), "horas": ent.get("horas"),
        }
        q["cards"].append(item)
        if p.get("status") in encerrados:
            q["finalizados"] += 1
            if p.get("status") == "Finalizado":
                entregas.append(item)
        else:
            q["em_andamento"] += 1
            andamento.append(item)
    entregas.sort(key=lambda e: str(e["concluido_em"] or ''), reverse=True)
    for q in quadros.values():
        q["responsaveis"] = sorted(q["responsaveis"])
        q["cards"].sort(key=lambda c: str(c.get("concluido_em") or c.get("prazo") or ''), reverse=True)
    # Quadros de produto primeiro, depois internos; mais cards no topo.
    lista_quadros = sorted(quadros.values(), key=lambda q: (not q["produto"], -q["total"]))

    primeiro = min((str(c["data"]) for c in contratos if c["data"]), default=None)
    return {
        "contratos": contratos,
        "entregas": entregas,
        "em_andamento": andamento,
        "quadros": lista_quadros,
        "total_contratos": len(contratos),
        "valor_total": (sum(float(c["valor"] or 0) for c in contratos) if pode_valor else None),
        "total_entregas": len(entregas),
        "cliente_desde": primeiro,
        "leads_ids": [l["id"] for l in leads],
    }


# ============================================================================
# GET /api/projetos/<id>/origem
# ============================================================================

@continuidade_bp.route('/api/projetos/<projeto_id>/origem', methods=['GET'])
def origem_do_projeto(projeto_id):
    """Origem comercial de um card: briefing da venda, cadastro do cliente,
    contrato, trajetória e -- para cobranças -- dados para faturar."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    p = _um("projetos", "*", "id", projeto_id)
    if not p or p.get("excluido_em"):
        return jsonify({"status": "erro", "mensagem": "Projeto não encontrado."}), 404
    if not _projeto_visivel(p):
        return jsonify({"status": "erro", "mensagem": "Sem acesso a este projeto."}), 403

    pode = _c('pode')
    pode_valor = pode('crm.valor.ver')
    passagem = dict(p.get("passagem") or {})
    lead = _um("leads", "*", "id", p["origem_lead_id"]) if p.get("origem_lead_id") else None
    cliente = _um("clientes", "id, nome_empresa, cnpj, email, telefone, cidade, estado, responsavel",
                  "id", p["cliente_id"]) if p.get("cliente_id") else None

    # Card criado à mão, sem lead nem passagem: não há origem a mostrar.
    tem_origem = bool(lead or not _vazio(passagem) or cliente)

    if not pode_valor:
        passagem.pop("valor_contrato", None)
        if passagem.get("entrega"):
            passagem["entrega"] = {k: v for k, v in passagem["entrega"].items() if k != "valor_contrato"}

    cadastro = None
    if lead or cliente:
        lead = lead or {}
        cliente = cliente or {}
        cadastro = {
            "empresa": cliente.get("nome_empresa") or lead.get("empresa") or p.get("empresa"),
            "contato": lead.get("contato"),
            "telefone": lead.get("telefone") or cliente.get("telefone"),
            "email": lead.get("email") or cliente.get("email"),
            "cnpj": cliente.get("cnpj") or lead.get("cnpj"),
            "cidade": lead.get("cidade") or cliente.get("cidade"),
            "estado": lead.get("estado") or cliente.get("estado"),
            "segmento": lead.get("segmento"),
            "origem": lead.get("origem"),
            "produto": lead.get("produto"),
            "responsavel_comercial": lead.get("responsavel"),
            "anotacoes": lead.get("anotacoes"),
            "valor_estimado": lead.get("valor_estimado") if pode_valor else None,
            "lead_id": lead.get("id"),
            "cliente_id": cliente.get("id"),
        }

    contrato = None
    info = (lead or {}).get("contrato_arquivo") or passagem.get("contrato") or {}
    if info.get("caminho"):
        contrato = {"nome": info.get("nome"), "enviado_em": info.get("enviado_em"),
                    "url": f"/api/projetos/{projeto_id}/contrato"}

    # Trajetória: eventos do lead (funil) e do card (fases), em ordem.
    trajetoria = []
    if lead:
        for m in _lista("lead_movimentos", "criado_em, de_funil, de_coluna, para_funil, para_coluna, autor",
                        lambda q: q.eq("lead_id", lead["id"]).order("criado_em"), 200):
            trajetoria.append({"quando": m.get("criado_em"), "tipo": "lead",
                               "titulo": f"{m.get('para_coluna')}",
                               "detalhe": f"{m.get('para_funil')} · {m.get('autor') or ''}".strip(' ·')})
        trajetoria.insert(0, {"quando": lead.get("criado_em"), "tipo": "lead",
                              "titulo": "Lead criado", "detalhe": lead.get("origem") or ''})
    if passagem.get("fechado_em"):
        trajetoria.append({"quando": passagem["fechado_em"], "tipo": "ganho",
                           "titulo": "Contrato ganho", "detalhe": passagem.get("closer") or ''})
    for m in _lista("projeto_movimentos", "criado_em, de_status, para_status, autor",
                    lambda q: q.eq("projeto_id", projeto_id).order("criado_em"), 200):
        trajetoria.append({"quando": m.get("criado_em"), "tipo": "card",
                           "titulo": m.get("para_status"), "detalhe": m.get("autor") or ''})
    trajetoria.sort(key=lambda e: str(e.get("quando") or ''))

    lote = None
    if p.get("lote_total"):
        irmaos = _lista("projetos", "id, lote_pos, status, responsavel, valor",
                        lambda q: q.eq("lote_id", p["lote_id"]).is_("excluido_em", "null").order("lote_pos"), 60)
        lote = {"pos": p.get("lote_pos"), "total": p.get("lote_total"),
                "valor_total": (next((i.get("valor") for i in irmaos if i.get("valor")), None)
                                if pode_valor else None),
                "cards": [{"id": i["id"], "pos": i.get("lote_pos"), "status": i.get("status"),
                           "responsavel": i.get("responsavel")} for i in irmaos]}

    conta = None
    if p.get("cliente_id") or (cadastro and cadastro.get("cnpj")):
        conta = _resumo_conta(p.get("cliente_id"), (cadastro or {}).get("cnpj"), pode_valor)
        conta.pop("leads_ids", None)

    return jsonify({
        "status": "sucesso",
        "tem_origem": tem_origem,
        "tipo": "cobranca" if passagem.get("faturamento") else ("produto" if _eh_produto(p.get("area")) else "interno"),
        "passagem": passagem,
        "cadastro": cadastro,
        "contrato": contrato,
        "trajetoria": trajetoria,
        "lote": lote,
        "conta": conta,
        "pode_valor": pode_valor,
    }), 200


# ============================================================================
# GET /api/projetos/<id>/contrato
# ============================================================================

@continuidade_bp.route('/api/projetos/<projeto_id>/contrato', methods=['GET'])
def contrato_do_projeto(projeto_id):
    """Link temporário do contrato a partir do card.

    Decisão: quem vê o card vê o contrato. O contrato acompanha o bastão
    -- e a rota do CRM exigiria `crm.lead.ver`, que a operação em geral
    não tem. O arquivo continua um só; só o link é gerado daqui.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    p = _um("projetos", "id, origem_lead_id, passagem, excluido_em, area, responsavel, empresa, cliente_id",
            "id", projeto_id)
    if not p or p.get("excluido_em"):
        return jsonify({"status": "erro", "mensagem": "Projeto não encontrado."}), 404
    if not _projeto_visivel(p):
        return jsonify({"status": "erro", "mensagem": "Sem acesso a este projeto."}), 403
    info = {}
    if p.get("origem_lead_id"):
        lead = _um("leads", "contrato_arquivo", "id", p["origem_lead_id"]) or {}
        info = lead.get("contrato_arquivo") or {}
    if not info.get("caminho"):
        info = (p.get("passagem") or {}).get("contrato") or {}
    if not info.get("caminho"):
        return jsonify({"status": "erro", "mensagem": "Este card não tem contrato."}), 404
    try:
        r = _c('supabase').storage.from_(_c('BUCKET_CONTRATOS')).create_signed_url(info["caminho"], 3600)
        url = r.get("signedURL") or r.get("signedUrl") or r.get("signed_url")
        if not url:
            raise RuntimeError("Storage nao devolveu o link")
        return jsonify({"status": "sucesso", "url": url, "nome": info.get("nome"), "expira_em": 3600}), 200
    except Exception as e:
        print("Erro em contrato_do_projeto:", e)
        return jsonify({"status": "erro", "mensagem": "Não foi possível gerar o link do contrato."}), 500


# ============================================================================
# GET /api/projetos/<id>/destinos
# ============================================================================

@continuidade_bp.route('/api/projetos/<projeto_id>/destinos', methods=['GET'])
def destinos_encerramento(projeto_id):
    """Para quem a cobrança e o lead de relacionamento vão, antes de quem
    finaliza confirmar. Destino sem responsável aparece como aviso na
    prévia em vez de o card nascer órfão em silêncio."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    p = _um("projetos", "id, area, origem_lead_id, cliente_id, passagem, responsavel, empresa", "id", projeto_id)
    if not p:
        return jsonify({"status": "erro", "mensagem": "Projeto não encontrado."}), 404
    quadro = _quadro_da_area(p.get("area"))
    resp_do_quadro = _c('responsavel_do_quadro')
    cob = resp_do_quadro('financeiro', 'cobranca')
    if not cob:
        pessoa, aguardando = _c('definir_dono')('financeiro')
        cob = None if aguardando else pessoa
    rel = resp_do_quadro(quadro, 'relacionamento') if quadro else None
    lead = _um("leads", "responsavel, contato, email, telefone", "id", p["origem_lead_id"]) if p.get("origem_lead_id") else None
    cliente = _um("clientes", "nome_empresa, cnpj, email, telefone", "id", p["cliente_id"]) if p.get("cliente_id") else None
    passagem = p.get("passagem") or {}
    return jsonify({
        "status": "sucesso",
        "cobranca": {"responsavel": (cob or {}).get("nome")},
        "relacionamento": {"responsavel": (rel or {}).get("nome") or (lead or {}).get("responsavel")},
        "faturamento_sugerido": {
            "contato": passagem.get("contato") or (lead or {}).get("contato"),
            "email": (cliente or {}).get("email") or (lead or {}).get("email"),
            "telefone": (cliente or {}).get("telefone") or (lead or {}).get("telefone"),
            "cnpj": (cliente or {}).get("cnpj"),
        },
        "tem_lead": bool(lead),
    }), 200


# ============================================================================
# GET /api/leads/<id>/conta
# ============================================================================

@continuidade_bp.route('/api/leads/<lead_id>/conta', methods=['GET'])
def conta_do_lead(lead_id):
    """A conta do cliente vista de um lead: por quais quadros passou, o
    que já foi vendido e entregue, o que está rodando, a entrega que
    originou este lead (relacionamento) e o contrato."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    lead = _um("leads", "*", "id", lead_id)
    if not lead:
        return jsonify({"status": "erro", "mensagem": "Lead não encontrado."}), 404
    pode = _c('pode')
    if not pode('crm.lead.ver', lead):
        return jsonify({"status": "erro", "mensagem": "Sem acesso a este lead."}), 403
    pode_valor = pode('crm.valor.ver')

    conta = _resumo_conta(lead.get("cliente_id"), lead.get("cnpj"), pode_valor)
    conta.pop("leads_ids", None)

    # Este lead é o de origem de algum card? (contrato -> operação)
    meus_cards = [c for q in conta["quadros"] for c in q["cards"]]
    entrega = dict(lead.get("entrega") or {})
    if not pode_valor:
        entrega.pop("valor_contrato", None)

    # Pai: o lead ganho que gerou este de relacionamento.
    pai = None
    if lead.get("lead_pai_id"):
        pp = _um("leads", "id, empresa, produto, responsavel, valor_estimado, movido_em, contrato_arquivo",
                 "id", lead["lead_pai_id"])
        if pp:
            pai = {"id": pp["id"], "produto": pp.get("produto"), "closer": pp.get("responsavel"),
                   "ganho_em": pp.get("movido_em"),
                   "valor": pp.get("valor_estimado") if pode_valor else None}

    # Briefing gravado nos cards deste lead: o que foi prometido na venda.
    # O lead de relacionamento não tem cards próprios: o briefing está
    # nos cards do lead que o gerou. Primeiro o card da entrega, depois
    # os cards deste lead, depois os do pai.
    prometido = None
    fontes = []
    if entrega.get("projeto_id"):
        fontes.append(lambda q: q.eq("id", entrega["projeto_id"]))
    fontes.append(lambda q: q.eq("origem_lead_id", lead_id).is_("excluido_em", "null"))
    if lead.get("lead_pai_id"):
        fontes.append(lambda q, pai_id=lead["lead_pai_id"]: q.eq("origem_lead_id", pai_id).is_("excluido_em", "null"))
    for filtro in fontes:
        for c in _lista("projetos", "passagem", filtro, 5):
            pg = c.get("passagem") or {}
            if pg.get("resumo"):
                prometido = {k: pg.get(k) for k in ("resumo", "contato", "cargo", "telefone",
                                                    "prazo_prometido", "atencao", "closer", "fechado_em")}
                break
        if prometido:
            break

    info = lead.get("contrato_arquivo") or {}
    contrato = ({"nome": info.get("nome"), "enviado_em": info.get("enviado_em"),
                 "url": f"/api/leads/{lead_id}/contrato",
                 "compartilhado": not str(info.get("caminho", "")).startswith(str(lead_id) + '/')}
                if info.get("caminho") else None)

    cliente = None
    if lead.get("cliente_id"):
        cliente = _um("clientes", "id, nome_empresa, cnpj, cidade, estado, responsavel, criado_em",
                      "id", lead["cliente_id"])

    return jsonify({
        "status": "sucesso",
        "conta": conta,
        "entrega": entrega,
        "prometido": prometido,
        "pai": pai,
        "contrato": contrato,
        "cliente": cliente,
        "passou_por_quadros": bool(meus_cards),
        "pode_valor": pode_valor,
    }), 200


# ============================================================================
# GET /api/clientes/por-cnpj?cnpj=
# ============================================================================

@continuidade_bp.route('/api/clientes/por-cnpj', methods=['GET'])
def cliente_pelo_cnpj():
    """Trava de duplicidade. A tela pergunta ao digitar o CNPJ; se já é
    cliente, mostra a conta e oferece "nova oportunidade" em vez de
    cadastro novo. O backend faz a mesma checagem no fechamento, então a
    tela é conveniência e o servidor é a garantia."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    cnpj = request.args.get('cnpj', '')
    dig = _c('so_digitos')(cnpj)
    if len(dig) != 14:
        return jsonify({"status": "sucesso", "existe": False, "motivo": "cnpj incompleto"}), 200
    c = _c('cliente_por_cnpj')(cnpj)
    if not c:
        # Mesma raiz (8 primeiros dígitos) = outra unidade do mesmo grupo.
        grupo = []
        try:
            for x in _c('_paginar')("clientes", "id, nome_empresa, cnpj",
                                    lambda q: q.is_("excluido_em", "null").not_.is_("cnpj", "null")):
                d2 = _c('so_digitos')(x.get("cnpj"))
                if len(d2) == 14 and d2[:8] == dig[:8]:
                    grupo.append({"id": x["id"], "nome": x.get("nome_empresa"), "cnpj": x.get("cnpj")})
        except Exception as e:
            print("Aviso: grupo por raiz:", e)
        return jsonify({"status": "sucesso", "existe": False, "mesmo_grupo": grupo}), 200
    pode_valor = _c('pode')('crm.valor.ver')
    conta = _resumo_conta(c["id"], c.get("cnpj"), pode_valor)
    return jsonify({
        "status": "sucesso", "existe": True,
        "cliente": {"id": c["id"], "nome": c.get("nome_empresa"), "cnpj": c.get("cnpj"),
                    "cidade": c.get("cidade"), "estado": c.get("estado"),
                    "responsavel": c.get("responsavel"), "desde": conta.get("cliente_desde") or c.get("criado_em")},
        "total_contratos": conta["total_contratos"],
        "valor_total": conta["valor_total"],
        "total_entregas": conta["total_entregas"],
        "em_andamento": len(conta["em_andamento"]),
        "ultima_entrega": (conta["entregas"][0] if conta["entregas"] else None),
    }), 200
