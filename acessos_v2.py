# -*- coding: utf-8 -*-
"""
core.cx · Acessos e Configurações (v2)
======================================

Módulo único e fechado que substitui o modelo de níveis e papéis por
quatro decisões guardadas na própria pessoa:

    admin      administra a plataforma ou não
    quadros    em quais quadros de trabalho atua
    alcance    quanto enxerga dentro deles (proprio | quadro)
    areas      quais telas da plataforma abre

Mais uma quinta, guardada por quadro em `quadro_executores`:

    responsável  em quais quadros pode receber card

POR QUE UM BLUEPRINT E NÃO CÓDIGO NOVO NO app.py
------------------------------------------------
Acesso é a parte do sistema em que um erro custa mais caro. Isolar tudo
num arquivo permite ler as regras inteiras de uma vez, em vez de caçá-las
entre cinco mil linhas de rotas de projeto e CRM. O `app.py` só registra
o blueprint e delega duas funções.

COMO CONVIVE COM O CÓDIGO EXISTENTE
-----------------------------------
As ~200 chamadas `pode('projeto.editar')` espalhadas pelo app continuam
funcionando sem edição. Este módulo não muda a pergunta: muda quem
responde. `montar_caps()` traduz o modelo novo para o mesmo mapa
{capacidade: escopo} que a sessão já carregava do banco.

Trocamos o construtor, não os 200 pontos de consumo.
"""

from functools import wraps

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   session, url_for)

acessos_bp = Blueprint('acessos_v2', __name__)


# ============================================================================
# LIGAÇÃO COM O app.py
#
# Injetadas uma vez na inicialização em vez de importadas: evita import
# circular (app.py importa este módulo, este módulo precisaria do app.py)
# e deixa o módulo testável com dublês.
# ============================================================================

_ctx = {}


def configurar(supabase, catalogo, arvore_quadros, areas, gerar_hash,
               registrar_auditoria):
    """Recebe do app.py o que este módulo precisa para funcionar."""
    _ctx['supabase'] = supabase
    _ctx['CATALOGO'] = catalogo
    _ctx['ARVORE'] = arvore_quadros
    _ctx['AREAS'] = areas
    _ctx['gerar_hash'] = gerar_hash
    _ctx['auditoria'] = registrar_auditoria


def _sb():
    return _ctx['supabase']


def _catalogo():
    return _ctx['CATALOGO']


def _quadros_lista():
    """[(chave, nome, icone)] na ordem da árvore de quadros."""
    return [(c, nome, ico) for c, nome, _p, ico, _s in _ctx['ARVORE']]


def _quadros_validos():
    return {c for c, _n, _i in _quadros_lista()}


def _areas_lista():
    """[(chave, nome, icone, descricao)]"""
    return list(_ctx['AREAS'])


def _areas_validas():
    return {a[0] for a in _areas_lista()}


# ============================================================================
# O MODELO DE PERMISSÃO
#
# Três listas explícitas, no código e não no banco: uma capacidade não
# pode existir sem alguém tê-la implementado, e ler o arquivo tem que
# bastar para saber quem pode o quê.
# ============================================================================

# Só administrador. Nunca liberadas por tela nem por quadro — são as que
# permitem mudar as próprias regras do jogo.
CAPS_ADMIN = (
    'auditoria.ver',          # registro de quem fez o quê
    'lixeira.purgar',         # remoção irreversível
    'cliente.portal.gerir',   # liberar acesso externo de cliente
    'feed.moderar',           # editar e apagar post de qualquer pessoa
    'feed.comunicado',        # falar em nome da empresa
)

# Todo interno tem, sempre. Não vira pergunta na tela porque não há
# decisão a tomar: são o trabalho do dia.
CAPS_LIBERADAS = (
    'projeto.ver',
    # Quem enxerga o card, edita o card. Não existe permissão separada
    # para editar: o que limita é o ALCANCE, resolvido em `pode()` pelo
    # nível daquele quadro. Sem esta linha, `projeto.editar` nunca entrava
    # na sessão e ninguém além do administrador conseguia mexer em card
    # nenhum -- nem no próprio.
    'projeto.editar',
    'projeto.excluir',        # vai para a lixeira, com registro de quem foi
    'projeto.solicitar',
    'tempo.registrar',
    'okr.ver',
    'feed.publicar',
    'comentario.excluir',
    'dados.exportar',
    'crm.valor.ver',
)

# Direcionar demanda não é permissão de pessoa, é papel de quadro: quem
# direciona é escolhido em Configurações, por quadro. Deixar isto em
# CAPS_LIBERADAS dava a todo mundo o poder de atribuir card em qualquer
# quadro -- inclusive nos que a pessoa nem acessa.
CAPS_POR_PAPEL_DE_QUADRO = ('projeto.atribuir',)

# Não são "tem ou não tem": são "vê só o seu ou vê o do quadro todo".
# Um seletor único move todas de uma vez, em vez de cinco decisões
# independentes que ninguém quer tomar uma a uma.
CAPS_ALCANCE = (
    'projeto.editar',
    'tempo.ver',
    'crm.lead.ver',
    'crm.painel.ver',
    'cliente.ver',
)

# Uma tela liberada em Acessos acende as capacidades daquela tela.
# Sem a tela, a pessoa não abre o módulo e não tem as capacidades dele.
CAPS_POR_TELA = {
    # Operar o funil e ver o resultado comercial são coisas diferentes:
    # quem trabalha os leads não necessariamente pode ver receita, ticket
    # médio e conversão por pessoa.
    'crm':          ('crm.lead.ver', 'crm.lead.editar', 'crm.lead.excluir'),
    'crm_painel':   ('crm.painel.ver',),
    'clientes':     ('cliente.ver', 'cliente.gerir'),
    'okr':          ('okr.ver', 'okr.gerir'),
    'dashboard':    ('dashboard.ver',),
    'lixeira':      ('lixeira.ver',),
    'feed':         ('feed.publicar',),
    'agenda':       ('tempo.registrar', 'tempo.ver'),
    # Configurar quadros e gerir acessos deixaram de ser exclusivos do
    # administrador: viraram telas que se liga para quem precisa. O
    # interruptor de admin continua existindo para quem responde por tudo.
    'configuracoes': (),
    'acessos':       ('usuario.gerir', 'papel.gerir'),
}

ALCANCES = ('proprio', 'quadro')
MODOS_QUADRO = ('direto', 'fila', 'rodizio')

# ----------------------------------------------------------------------------
# NÍVEL POR QUADRO
#
# Três estados, e só três. Cada um a mais é uma pergunta que quem
# configura precisa responder doze vezes, uma por quadro.
#
#   sem acesso  o quadro não aparece
#   proprio     vê o quadro, mas os detalhes só dos próprios cards
#   tudo        vê e edita o trabalho de todos naquele quadro
#
# "Pode editar" e "pode adicionar" não viraram níveis separados de
# propósito: quem enxerga o card do colega e não pode mexer nele acaba
# pedindo por mensagem, e o controle vira burocracia sem virar segurança.
# Ver e editar andam juntos; o que muda é o alcance.
# ----------------------------------------------------------------------------
NIVEIS_QUADRO = ('proprio', 'tudo')

# Abrir solicitação em qualquer quadro vale para todo mundo, inclusive em
# quadro sem acesso: pedir algo ao Financeiro não exige enxergar o
# Financeiro. Por isso `projeto.solicitar` está em CAPS_LIBERADAS.

# ----------------------------------------------------------------------------
# PERFIS PRONTOS
#
# Configurar doze quadros e sete telas a mão, para treze pessoas, é onde
# o modelo anterior falhava na prática: dava trabalho e ninguém revisava.
# O perfil preenche tudo de uma vez; a exceção se ajusta depois, quadro a
# quadro. Perfil é ponto de partida, não jaula.
# ----------------------------------------------------------------------------
PERFIS = {
    'admin': {
        'nome': 'Administrador',
        'descricao': 'Vê e faz tudo, inclusive configurar acessos e apagar em definitivo.',
        'admin': True,
    },
    'diretoria': {
        'nome': 'Diretoria',
        'descricao': 'Vê o trabalho de todos, em todos os quadros, e os dois '
                     'dashboards. Sem Acessos, Configurações e Lixeira.',
        'admin': False,
        'nivel_padrao': 'tudo',
        'telas': ('feed', 'agenda', 'crm', 'crm_painel', 'dashboard', 'okr', 'clientes'),
    },
    'colaborador': {
        'nome': 'Colaborador',
        'descricao': 'Vê os quadros em que atua, mas só os próprios cards. '
                     'Sem dashboards, Lixeira, Configurações e Acessos.',
        'admin': False,
        'nivel_padrao': 'proprio',
        'telas': ('feed', 'agenda', 'crm', 'okr', 'clientes'),
    },
}

# Papéis operacionais por quadro, gravados em `quadro_responsaveis`.
PAPEIS_OPERACIONAIS = ('direciona', 'cobranca', 'relacionamento')


def montar_caps(usuario):
    """Traduz o modelo novo para o mapa {capacidade: escopo} da sessão.

    É o coração do módulo. Tudo o que o resto do sistema pergunta com
    `pode(...)` sai daqui.

    Escopos possíveis por capacidade vêm do CATALOGO. Quando o escopo
    desejado não existe para aquela capacidade, cai no mais próximo
    disponível — nunca em algo mais permissivo do que 'tudo'.
    """
    catalogo = _catalogo()

    # Administrador tem tudo, em escopo total. Sem meio-termo: quem liga
    # o interruptor precisa entender exatamente o que está dando.
    if usuario.get('admin'):
        return {cap: 'tudo' for cap in catalogo}

    # Externo (portal do cliente) não entra neste modelo: continua com o
    # fluxo de leitura restrita do portal, definido em outro lugar.
    if (usuario.get('tipo_usuario') or 'interno') == 'externo':
        return {}

    # O alcance global vira o MAIOR nível entre os quadros da pessoa.
    # Ele ainda serve às capacidades que não pertencem a quadro nenhum --
    # CRM e Clientes, por exemplo. As de projeto usam o nível do quadro
    # do card, resolvido em `pode()`.
    acessos = _acessos_do(usuario)
    alcance = 'quadro' if 'tudo' in acessos.values() else 'proprio'
    telas = set(usuario.get('areas') or [])

    # As telas liberadas acendem as capacidades dos seus módulos.
    liberadas = set(CAPS_LIBERADAS)
    for tela in telas:
        liberadas.update(CAPS_POR_TELA.get(tela, ()))

    caps = {}
    for cap in liberadas:
        if cap in CAPS_ADMIN or cap not in catalogo:
            continue
        escopos = catalogo[cap][3]

        # Capacidade binária (sem escopo declarado): tem ou não tem.
        if not escopos:
            caps[cap] = 'tudo'
            continue

        # Capacidade de alcance: segue a escolha da pessoa.
        if cap in CAPS_ALCANCE:
            caps[cap] = alcance if alcance in escopos else (
                'tudo' if 'tudo' in escopos else escopos[-1])
            continue

        # Demais: no máximo o quadro. Amarrar em 'quadro' é o que impede
        # alguém de enxergar card de um quadro que nem consegue abrir —
        # 'tudo' ignoraria a lista de quadros da pessoa por completo.
        caps[cap] = 'quadro' if 'quadro' in escopos else (
            'tudo' if 'tudo' in escopos else escopos[-1])

    return caps


def _acessos_do(usuario):
    """Mapa {quadro: nivel} da pessoa, validado.

    Aceita o formato novo (`acessos`) e reconstrói a partir do antigo
    (`quadros` + `alcance`) quando ele ainda não existe — assim ninguém
    perde acesso entre o deploy do código e a execução da migração.
    """
    bruto = usuario.get('acessos')
    if isinstance(bruto, dict) and bruto:
        return {q: n for q, n in bruto.items()
                if q in _quadros_validos() and n in NIVEIS_QUADRO}
    antigo = usuario.get('alcance')
    nivel = 'tudo' if antigo == 'quadro' else 'proprio'
    return {q: nivel for q in (usuario.get('quadros') or []) if q in _quadros_validos()}


def aplicar_na_sessao(usuario):
    """Monta a sessão de permissões no login.

    Também alimenta `nivel_acesso` e `perm_modulos`, que a barra lateral
    e as telas antigas ainda leem. Manter os dois em dia é o que permite
    trocar o modelo sem reescrever todos os templates no mesmo dia.
    """
    admin = bool(usuario.get('admin'))
    acessos = _acessos_do(usuario)
    # Administrador enxerga tudo em todos, sem depender do que está
    # gravado: o interruptor de admin é a fonte da verdade.
    if admin:
        acessos = {c: 'tudo' for c, _n, _i in _quadros_lista()}
    quadros = sorted(acessos.keys())
    areas = list(_areas_validas()) if admin else [
        a for a in (usuario.get('areas') or []) if a in _areas_validas()]

    session['admin'] = admin
    session['acessos'] = acessos
    session['alcance'] = 'quadro' if 'tudo' in acessos.values() else 'proprio'
    session['quadros'] = quadros
    session['areas'] = areas
    session['caps'] = montar_caps(usuario)
    session['papel_id'] = None
    session['papel_nome'] = 'Administrador' if admin else 'Personalizado'
    session['equipe'] = usuario.get('equipe')

    # Ponte com o que já existe. A sidebar decide por `nivel_acesso` e
    # `perm_modulos`; entregar os dois coerentes com o modelo novo evita
    # menu fantasma (item visível que leva a um 403).
    session['nivel_acesso'] = 'admin' if admin else 'personalizado'
    session['perm_modulos'] = quadros + areas + (['configuracoes'] if admin else [])


def sou_admin():
    """Administrador pelo modelo novo, com queda para o antigo.

    A queda existe para quem já estava logado quando o código subiu: sem
    ela, todo mundo com sessão aberta perderia o acesso no meio do dia.
    """
    if session.get('admin') is True:
        return True
    return session.get('nivel_acesso') == 'admin'


def exige_admin(fn):
    """Decorador de rota de API. Distingue não logado de sem permissão:
    o front precisa saber se manda para o login ou mostra o aviso."""
    @wraps(fn)
    def interna(*args, **kwargs):
        if 'usuario_id' not in session:
            return jsonify({"status": "erro", "mensagem": "Sessão expirada."}), 401
        if not (sou_admin() or 'acessos' in (session.get('areas') or [])
                or 'configuracoes' in (session.get('areas') or [])):
            return jsonify({"status": "erro",
                            "mensagem": "Você não tem acesso a esta área."}), 403
        return fn(*args, **kwargs)
    return interna


def _erro(mensagem, e=None, codigo=500):
    """Resposta de erro padronizada. Ferramenta interna e autenticada:
    devolver o motivo economiza uma ida ao log a cada problema."""
    corpo = {"status": "erro", "mensagem": mensagem}
    if e is not None:
        print(f"[acessos_v2] {mensagem} :: {e}")
        corpo["detalhe"] = str(e)[:300]
    return jsonify(corpo), codigo


def _auditar(acao, recurso, alvo_id, detalhe=None):
    try:
        _ctx['auditoria'](acao, recurso, alvo_id, detalhe or {})
    except Exception as e:
        print("[acessos_v2] auditoria nao registrada:", e)


# ============================================================================
# PÁGINAS
# ============================================================================

@acessos_bp.route('/acessos')
def pagina_acessos():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    if not (sou_admin() or 'acessos' in (session.get('areas') or [])):
        return redirect(url_for('index'))
    return render_template('acessos.html',
                           usuario_nome=session.get('usuario_nome', ''),
                           nivel_acesso=session.get('nivel_acesso', ''),
                           tipo_usuario=session.get('tipo_usuario', 'interno'),
                           papel_externo=session.get('papel_externo', ''),
                           perm_modulos=session.get('perm_modulos', []))


@acessos_bp.route('/configuracoes')
def pagina_configuracoes():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    if not (sou_admin() or 'configuracoes' in (session.get('areas') or [])):
        return redirect(url_for('index'))
    return render_template('configuracoes.html',
                           usuario_nome=session.get('usuario_nome', ''),
                           nivel_acesso=session.get('nivel_acesso', ''),
                           tipo_usuario=session.get('tipo_usuario', 'interno'),
                           papel_externo=session.get('papel_externo', ''),
                           perm_modulos=session.get('perm_modulos', []))


# ============================================================================
# CATÁLOGO — o que as duas telas precisam saber sobre o mundo
# ============================================================================

@acessos_bp.route('/api/v2/catalogo', methods=['GET'])
@exige_admin
def catalogo():
    """Quadros, telas e o texto das opções. Uma chamada, sem hardcode
    no JavaScript: quadro novo na árvore aparece nas telas sozinho."""
    return jsonify({
        "status": "sucesso",
        "quadros": [{"chave": c, "nome": n, "icone": i} for c, n, i in _quadros_lista()],
        "telas": [{"chave": c, "nome": n, "icone": i, "descricao": d}
                  for c, n, i, d in _areas_lista()],
        "niveis": [
            {"chave": "", "nome": "Sem acesso", "curto": "—",
             "descricao": "O quadro não aparece para esta pessoa."},
            {"chave": "proprio", "nome": "Só os seus", "curto": "seus",
             "descricao": "Vê o quadro, mas os detalhes e o tempo lançado só dos "
                          "cards em que é responsável."},
            {"chave": "tudo", "nome": "Vê tudo", "curto": "tudo",
             "descricao": "Vê e edita o trabalho de todos naquele quadro."},
        ],
        # O perfil viaja completo -- nível e telas junto -- para a tela
        # poder aplicá-lo na hora, sem esperar a volta do servidor. O
        # servidor continua sendo quem define: a tela só espelha.
        "perfis": [
            {"chave": c, "nome": p["nome"], "descricao": p["descricao"],
             "admin": p.get("admin", False),
             "nivel_padrao": p.get("nivel_padrao"),
             "telas": list(p.get("telas", ()))}
            for c, p in PERFIS.items()
        ],
        "modos": [
            {"chave": "direto", "nome": "Direto", "icone": "bolt",
             "descricao": "Uma pessoa recebe todos os cards. Sem espera."},
            {"chave": "fila", "nome": "Fila", "icone": "alt_route",
             "descricao": "O card espera alguém escolher quem executa."},
            {"chave": "rodizio", "nome": "Rodízio", "icone": "shuffle",
             "descricao": "Vai para quem tem menos cards em aberto no quadro."},
        ],
        "liberado_sempre": [
            _catalogo()[c][1] for c in CAPS_LIBERADAS if c in _catalogo()
        ],
    }), 200


# ============================================================================
# ACESSOS — pessoas
# ============================================================================

def _pessoa_publica(u, responsavel_em):
    """Formato que a tela consome. O hash nunca sai do servidor: vira um
    booleano, que é tudo o que a tela precisa saber."""
    return {
        "id": str(u["id"]),
        "nome": u.get("nome") or "",
        "email": u.get("email") or "",
        "cargo": u.get("cargo") or "",
        "telefone": u.get("telefone") or "",
        "ativo": u.get("ativo") is not False,
        "admin": bool(u.get("admin")),
        "acessos": _acessos_do(u),
        "alcance": u.get("alcance") if u.get("alcance") in ALCANCES else 'proprio',
        "quadros": [q for q in (u.get("quadros") or []) if q in _quadros_validos()],
        "perfil": _perfil_de(u),
        "telas": [a for a in (u.get("areas") or []) if a in _areas_validas()],
        "responsavel_em": sorted(responsavel_em.get(str(u["id"]), [])),
        "ultimo_acesso": u.get("ultimo_acesso"),
        "tem_senha": bool(u.get("senha_hash")),
    }


def _perfil_de(u):
    """Qual perfil descreve esta pessoa hoje, ou 'personalizado'.

    Serve para a tela mostrar o ponto de partida sem obrigar ninguém a
    escolher de novo -- e para deixar claro quando alguém saiu do padrão.
    """
    if u.get('admin'):
        return 'admin'
    acessos = _acessos_do(u)
    todos = {c for c, _n, _i in _quadros_lista()}
    telas = set(u.get('areas') or [])
    for chave in ('diretoria', 'colaborador'):
        p = PERFIS[chave]
        esperado = {c: p['nivel_padrao'] for c in todos}
        if acessos == esperado and telas == set(p['telas']):
            return chave
    return 'personalizado'


def _mapa_responsaveis():
    """{usuario_id: [quadros]} — quem pode receber card onde."""
    mapa = {}
    try:
        r = (_sb().table("quadro_executores").select("quadro, usuario_id").execute())
        for linha in (r.data or []):
            uid = str(linha.get("usuario_id") or '')
            if uid:
                mapa.setdefault(uid, []).append(linha.get("quadro"))
    except Exception as e:
        print("[acessos_v2] quadro_executores indisponivel:", e)
    return mapa


@acessos_bp.route('/api/v2/acessos/pessoas', methods=['GET'])
@exige_admin
def listar_pessoas():
    """Lista para a tabela. Duas consultas, não uma por pessoa: com treze
    hoje não faria diferença, com cem faria."""
    try:
        res = (_sb().table("usuarios")
               .select("id, nome, email, cargo, telefone, ativo, admin, alcance, "
                       "quadros, areas, ultimo_acesso, senha_hash, tipo_usuario")
               .order("nome").execute())
        internos = [u for u in (res.data or [])
                    if (u.get("tipo_usuario") or 'interno') == 'interno']
        resp = _mapa_responsaveis()
        pessoas = [_pessoa_publica(u, resp) for u in internos]
        return jsonify({
            "status": "sucesso",
            "pessoas": pessoas,
            "total": len(pessoas),
            "administradores": sum(1 for p in pessoas if p["admin"] and p["ativo"]),
        }), 200
    except Exception as e:
        return _erro("Erro ao carregar as pessoas.", e)


@acessos_bp.route('/api/v2/acessos/pessoas', methods=['POST'])
@exige_admin
def criar_pessoa():
    try:
        d = request.get_json(silent=True) or {}
        nome = (d.get("nome") or "").strip()
        email = (d.get("email") or "").strip().lower()
        senha = d.get("senha") or ""

        if not nome:
            return _erro("Informe o nome.", codigo=400)
        if "@" not in email or "." not in email.split("@")[-1]:
            return _erro("Informe um e-mail válido.", codigo=400)
        if len(senha) < 8:
            return _erro("A senha precisa de pelo menos 8 caracteres.", codigo=400)

        existe = _sb().table("usuarios").select("id").eq("email", email).limit(1).execute()
        if existe.data:
            return _erro("Já existe alguém com este e-mail.", codigo=409)

        novo = {
            "nome": nome,
            "email": email,
            "cargo": (d.get("cargo") or "").strip() or None,
            "telefone": (d.get("telefone") or "").strip() or None,
            "tipo_usuario": "interno",
            "ativo": True,
            "admin": False,
            "alcance": "proprio",
            "quadros": [],
            "areas": [],
            "senha_hash": _ctx['gerar_hash'](senha),
            # Coerência com a ponte da sessão: quem não é admin é
            # personalizado, e a sidebar já sabe ler isso.
            "nivel_acesso": "personalizado",
            "perm_modulos": [],
            "ajustes": {},
        }
        res = _sb().table("usuarios").insert(novo).execute()
        criado = (res.data or [{}])[0]
        criado.pop("senha_hash", None)
        criado.pop("senha", None)
        _auditar("pessoa_criada", "usuario", criado.get("id"),
                 {"nome": nome, "email": email})
        return jsonify({"status": "sucesso",
                        "pessoa": _pessoa_publica(criado, {})}), 201
    except Exception as e:
        return _erro("Erro ao cadastrar a pessoa.", e)


@acessos_bp.route('/api/v2/acessos/pessoas/<usuario_id>', methods=['PUT'])
@exige_admin
def salvar_pessoa(usuario_id):
    """Grava a página da pessoa inteira numa transação lógica.

    Salvar tudo de uma vez, e não campo a campo, é o que impede estado
    incoerente: desmarcar um quadro e falhar ao limpar a responsabilidade
    deixaria alguém recebendo card de um quadro que não abre mais.
    """
    try:
        d = request.get_json(silent=True) or {}

        atual = (_sb().table("usuarios")
                 .select("id, nome, admin, ativo, quadros, areas, alcance, tipo_usuario")
                 .eq("id", usuario_id).limit(1).execute())
        if not atual.data:
            return _erro("Pessoa não encontrada.", codigo=404)
        antes = atual.data[0]

        if (antes.get("tipo_usuario") or 'interno') == 'externo':
            return _erro("Usuário externo é gerido pelo portal do cliente.", codigo=400)

        upd = {}

        if "admin" in d:
            upd["admin"] = bool(d["admin"])
        if "ativo" in d:
            upd["ativo"] = bool(d["ativo"])
        if "alcance" in d:
            if d["alcance"] not in ALCANCES:
                return _erro("Alcance inválido.", codigo=400)
            upd["alcance"] = d["alcance"]
        if "cargo" in d:
            upd["cargo"] = (d["cargo"] or "").strip() or None
        if "telefone" in d:
            upd["telefone"] = (d["telefone"] or "").strip() or None

        quadros = None

        # Perfil preenche tudo de uma vez; a exceção vem depois, quadro a
        # quadro. Aplicar o perfil e as exceções no mesmo pedido faria a
        # ordem importar -- por isso o perfil é resolvido primeiro.
        if d.get("perfil") in PERFIS:
            p = PERFIS[d["perfil"]]
            upd["admin"] = bool(p.get("admin"))
            if not p.get("admin"):
                nivel = p.get("nivel_padrao", "proprio")
                d["acessos"] = {c: nivel for c, _n, _i in _quadros_lista()}
                d["telas"] = list(p.get("telas", ()))

        if "acessos" in d:
            mapa = {q: n for q, n in (d["acessos"] or {}).items()
                    if q in _quadros_validos() and n in NIVEIS_QUADRO}
            upd["acessos"] = mapa
            quadros = sorted(mapa.keys())
            upd["quadros"] = quadros
            # `alcance` continua alimentado para o que ainda o lê.
            upd["alcance"] = 'quadro' if 'tudo' in mapa.values() else 'proprio'
        elif "quadros" in d:
            quadros = [q for q in (d["quadros"] or []) if q in _quadros_validos()]
            upd["quadros"] = quadros
        if "telas" in d:
            upd["areas"] = [a for a in (d["telas"] or []) if a in _areas_validas()]

        virou_admin = upd.get("admin") is True
        deixou_admin = ("admin" in upd and upd["admin"] is False) or upd.get("ativo") is False

        # Trava: nunca ficar sem administrador ativo. O banco também
        # barra por gatilho; a aplicação barra antes para poder devolver
        # uma mensagem que faça sentido em vez de um erro de SQL.
        if antes.get("admin") and antes.get("ativo") is not False and deixou_admin:
            outros = (_sb().table("usuarios").select("id")
                      .eq("admin", True).eq("ativo", True)
                      .neq("id", usuario_id).execute()).data or []
            if not outros:
                return _erro("Precisa sobrar ao menos uma pessoa ativa com acesso "
                             "de administrador.", codigo=400)

        # Ninguém tira o próprio acesso de administrador sem querer.
        if str(session.get('usuario_id')) == str(usuario_id) and deixou_admin:
            return _erro("Você não pode remover o próprio acesso de administrador. "
                         "Peça a outro administrador.", codigo=400)

        # Administrador tem todos os quadros e telas por definição:
        # gravar o conjunto completo evita que a tela precise inventar
        # exceções e que a sidebar fique com buraco.
        if virou_admin:
            todos = [c for c, _n, _i in _quadros_lista()]
            upd["quadros"] = todos
            upd["acessos"] = {c: "tudo" for c in todos}
            upd["areas"] = list(_areas_validas())
            upd["alcance"] = "quadro"
            quadros = todos

        upd["nivel_acesso"] = 'admin' if upd.get(
            "admin", antes.get("admin")) else 'personalizado'
        upd["perm_modulos"] = (upd.get("quadros", antes.get("quadros") or [])
                               + upd.get("areas", antes.get("areas") or []))

        if upd:
            _sb().table("usuarios").update(upd).eq("id", usuario_id).execute()

        # --- responsabilidade por quadro ---------------------------------
        if "responsavel_em" in d or quadros is not None:
            base = quadros if quadros is not None else (antes.get("quadros") or [])
            pedidos = d.get("responsavel_em")
            if pedidos is None:
                # Só os quadros mudaram: preserva o que já existia e
                # descarta o que saiu.
                atuais = _mapa_responsaveis().get(str(usuario_id), [])
                pedidos = [q for q in atuais if q in base]
            # Marcar quadro que a pessoa não acessa criaria alguém que
            # recebe card sem conseguir abrir a tela.
            desejados = {q for q in (pedidos or []) if q in base and q in _quadros_validos()}
            _sincronizar_responsavel(usuario_id, desejados)

        _auditar("acesso_alterado", "usuario", usuario_id, {
            "campos": sorted(upd.keys()),
            "admin": upd.get("admin"),
            "alcance": upd.get("alcance"),
            "quadros": len(upd.get("quadros", [])) if "quadros" in upd else None,
        })
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return _erro("Erro ao salvar o acesso.", e)


def _sincronizar_responsavel(usuario_id, desejados):
    """Aplica só a diferença em `quadro_executores`.

    Apagar tudo e reinserir seria mais curto, mas perderia a data de
    criação — que é o critério de desempate do rodízio e do executor
    padrão. Sincronizar preserva a ordem histórica.
    """
    try:
        atuais = {linha["quadro"] for linha in
                  ((_sb().table("quadro_executores").select("quadro")
                    .eq("usuario_id", usuario_id).execute()).data or [])}
    except Exception as e:
        print("[acessos_v2] leitura de executores:", e)
        return

    for quadro in (atuais - desejados):
        try:
            (_sb().table("quadro_executores").delete()
             .eq("usuario_id", usuario_id).eq("quadro", quadro).execute())
            # Se essa pessoa era o executor padrão do quadro, o modo
            # Direto ficaria apontando para alguém que já não recebe.
            (_sb().table("quadro_config")
             .update({"executor_padrao": None})
             .eq("quadro", quadro).eq("executor_padrao", usuario_id).execute())
        except Exception as e:
            print(f"[acessos_v2] remover executor {quadro}:", e)

    novos = [{"quadro": q, "usuario_id": usuario_id} for q in (desejados - atuais)]
    if novos:
        try:
            _sb().table("quadro_executores").insert(novos).execute()
        except Exception as e:
            print("[acessos_v2] inserir executores:", e)


@acessos_bp.route('/api/v2/acessos/pessoas/<usuario_id>/senha', methods=['PUT'])
@exige_admin
def redefinir_senha(usuario_id):
    """Define uma senha nova. Quem redefine nunca vê a antiga — ela não
    existe em texto puro. A pessoa recebe a nova por fora e troca depois."""
    try:
        senha = (request.get_json(silent=True) or {}).get("senha") or ""
        if len(senha) < 8:
            return _erro("A senha precisa de pelo menos 8 caracteres.", codigo=400)
        _sb().table("usuarios").update({
            "senha_hash": _ctx['gerar_hash'](senha),
            # String vazia, e nao None: a coluna `senha` e NOT NULL. Gravar
            # null derrubava o update inteiro, entao redefinir senha pela
            # tela de Acessos nunca funcionou -- devolvia erro sempre.
            "senha": "",
        }).eq("id", usuario_id).execute()
        _auditar("senha_redefinida", "usuario", usuario_id, {})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return _erro("Erro ao redefinir a senha.", e)


@acessos_bp.route('/api/v2/acessos/registro', methods=['GET'])
@exige_admin
def registro():
    """Últimas alterações de acesso. Limite fixo: a tela é para conferir
    o que mudou esta semana, não para auditoria forense."""
    try:
        r = (_sb().table("auditoria").select("*")
             .in_("acao", ["acesso_alterado", "pessoa_criada", "senha_redefinida",
                           "quadro_configurado", "responsavel_alterado"])
             .order("criado_em", desc=True).limit(120).execute())
        return jsonify({"status": "sucesso", "registros": r.data or []}), 200
    except Exception as e:
        return _erro("Erro ao carregar o registro.", e)


# ============================================================================
# CONFIGURAÇÕES — quadros
# ============================================================================

@acessos_bp.route('/api/v2/config/quadros', methods=['GET'])
@exige_admin
def listar_quadros():
    """Como cada quadro distribui os cards que chegam.

    `candidatos` é a lista de quem foi marcado em Acessos: a tela de
    Configurações escolhe entre eles e nunca inventa nomes. Uma decisão,
    um lugar.
    """
    try:
        configs, resp, execs, carga = {}, {}, {}, {}

        try:
            for c in ((_sb().table("quadro_config").select("*").execute()).data or []):
                configs[c["quadro"]] = c
        except Exception as e:
            print("[acessos_v2] quadro_config:", e)

        try:
            for r in ((_sb().table("quadro_responsaveis").select("*").execute()).data or []):
                resp.setdefault(r["quadro"], {})[r["papel"]] = str(r.get("usuario_id") or '')
        except Exception as e:
            print("[acessos_v2] quadro_responsaveis:", e)

        try:
            for e_ in ((_sb().table("quadro_executores")
                        .select("quadro, usuario_id").execute()).data or []):
                execs.setdefault(e_["quadro"], []).append(str(e_.get("usuario_id") or ''))
        except Exception as e:
            print("[acessos_v2] quadro_executores:", e)

        pessoas = (_sb().table("usuarios")
                   .select("id, nome, email, ativo, admin, quadros, tipo_usuario")
                   .order("nome").execute()).data or []
        internos = [p for p in pessoas
                    if p.get("ativo") is not False
                    and (p.get("tipo_usuario") or 'interno') == 'interno']
        por_id = {str(p["id"]): p for p in internos}

        # Cards em aberto e esperando dono, agrupados por área.
        try:
            r = (_sb().table("projetos")
                 .select("area, status, aguardando_responsavel")
                 .is_("excluido_em", "null").execute())
            for p in (r.data or []):
                if p.get("status") in ('Finalizado', 'Cancelado'):
                    continue
                d_ = carga.setdefault(p.get("area"), {"abertos": 0, "esperando": 0})
                d_["abertos"] += 1
                if p.get("aguardando_responsavel"):
                    d_["esperando"] += 1
        except Exception as e:
            print("[acessos_v2] carga dos quadros:", e)

        saida = []
        for chave, nome, produto, icone, subs in _ctx['ARVORE']:
            cfg = configs.get(chave, {})
            marcados = [uid for uid in execs.get(chave, []) if uid in por_id]
            padrao = str(cfg.get("executor_padrao") or '')
            if padrao not in marcados:
                padrao = ''      # apontava para quem já não pode receber

            c = carga.get(nome, {})
            saida.append({
                "chave": chave,
                "nome": nome,
                "icone": icone,
                "produto": produto,
                "modo": cfg.get("modo") if cfg.get("modo") in MODOS_QUADRO else 'fila',
                "executor_padrao": padrao,
                "direciona": resp.get(chave, {}).get("direciona") or '',
                "cobranca": resp.get(chave, {}).get("cobranca") or '',
                "candidatos": [{"id": uid, "nome": por_id[uid].get("nome")}
                               for uid in marcados],
                # Quem direciona e quem cobra não precisa receber card:
                # basta acessar o quadro.
                "com_acesso": [{"id": str(p["id"]), "nome": p.get("nome")}
                               for p in internos
                               if p.get("admin") or chave in (p.get("quadros") or [])],
                "abertos": c.get("abertos", 0),
                "esperando": c.get("esperando", 0),
                "atualizado_em": cfg.get("atualizado_em"),
                "atualizado_por": cfg.get("atualizado_por"),
            })

        return jsonify({"status": "sucesso", "quadros": saida}), 200
    except Exception as e:
        return _erro("Erro ao carregar os quadros.", e)


@acessos_bp.route('/api/v2/config/quadros/<quadro>', methods=['PUT'])
@exige_admin
def salvar_quadro(quadro):
    """Grava modo, executor padrão e papéis operacionais de um quadro."""
    from datetime import datetime, timezone

    if quadro not in _quadros_validos():
        return _erro("Quadro inválido.", codigo=400)
    try:
        d = request.get_json(silent=True) or {}
        modo = d.get("modo")
        if modo not in MODOS_QUADRO:
            return _erro("Modo de distribuição inválido.", codigo=400)

        marcados = {str(x.get("usuario_id") or '') for x in
                    ((_sb().table("quadro_executores").select("usuario_id")
                      .eq("quadro", quadro).execute()).data or [])}
        marcados.discard('')

        executor = str(d.get("executor_padrao") or '') or None

        # Validações que descrevem a regra de negócio, não o formulário.
        if modo == 'direto':
            if not executor:
                return _erro("No modo Direto, escolha quem recebe os cards.", codigo=400)
            if executor not in marcados:
                return _erro("Essa pessoa não está marcada para receber card neste "
                             "quadro. Marque em Acessos antes.", codigo=400)
        elif modo == 'rodizio':
            if len(marcados) < 2:
                return _erro("O rodízio precisa de pelo menos duas pessoas marcadas "
                             "como responsáveis em Acessos.", codigo=400)
            executor = None
        else:                       # fila
            if not marcados:
                return _erro("Ninguém pode receber card neste quadro. Marque alguém "
                             "como responsável em Acessos.", codigo=400)
            if not d.get("direciona"):
                return _erro("No modo Fila, escolha quem direciona os cards.", codigo=400)
            executor = None

        agora = datetime.now(timezone.utc).isoformat()
        _sb().table("quadro_config").upsert({
            "quadro": quadro,
            "modo": modo,
            "executor_padrao": executor,
            "atualizado_em": agora,
            "atualizado_por": session.get('usuario_nome'),
        }, on_conflict="quadro").execute()

        for papel in PAPEIS_OPERACIONAIS:
            if papel not in d:
                continue
            _sb().table("quadro_responsaveis").upsert({
                "quadro": quadro,
                "papel": papel,
                "usuario_id": d.get(papel) or None,
                "atualizado_em": agora,
            }, on_conflict="quadro,papel").execute()

        _auditar("quadro_configurado", "quadro", quadro,
                 {"modo": modo, "candidatos": len(marcados)})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return _erro("Erro ao salvar a configuração do quadro.", e)
