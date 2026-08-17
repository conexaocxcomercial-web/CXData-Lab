from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from supabase import create_client, Client
from datetime import datetime, timezone, timedelta
import uuid

# Fuso horário de Brasília (UTC-3). Usado para gravar datas de projeto
# de forma consistente com a realidade local — evita erro de "um dia" na
# virada do ciclo de comissionamento (20 a 20).
FUSO_BR = timezone(timedelta(hours=-3))
def agora_br():
    """Retorna o datetime atual no horário de Brasília, em ISO."""
    return datetime.now(FUSO_BR).isoformat()
def hoje_br():
    """Retorna a data de hoje (date) no horário de Brasília."""
    return datetime.now(FUSO_BR).date()
import bcrypt
import secrets
import string
import os

app = Flask(__name__)
# CHAVE DE SESSÃO: lê de variável de ambiente, com fallback para não quebrar local
# PENDÊNCIA DE SEGURANÇA: o valor padrão permite forjar sessão de admin.
# Definir FLASK_SECRET_KEY no Vercel e remover o padrão.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "cxdata_chave_mestra_oficial_2026_!@")
app.permanent_session_lifetime = timedelta(days=7)

# CREDENCIAIS SUPABASE
# Preferência: SUPABASE_SERVICE_KEY (service_role, passa por cima do RLS)
# > SUPABASE_KEY (anon) > padrão embutido.
#
# PENDÊNCIA DE SEGURANÇA: o padrão embutido vaza junto com o repositório.
# Ao fechar: repositório privado, chaves rotacionadas, variáveis no Vercel
# e estes padrões removidos.
URL = os.environ.get("SUPABASE_URL", "https://udqeheyyhvqlwejdwkbj.supabase.co")
KEY = (os.environ.get("SUPABASE_SERVICE_KEY")
       or os.environ.get("SUPABASE_KEY")
       or "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVkcWVoZXl5aHZxbHdlamR3a2JqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM0MTk3NTksImV4cCI6MjA4ODk5NTc1OX0.qo9kF_dcrVLycg0XV9dnFyIH2euHAC8FISbkgv3KNrQ")
supabase: Client = create_client(URL, KEY)

# ============================================================
# ACESSOS v2 -- modelo de permissao em modulo separado
#
# Acesso e a parte do sistema em que um erro custa mais caro.
# Isolar as regras num arquivo permite le-las inteiras de uma vez,
# em vez de caca-las entre cinco mil linhas de rotas.
#
# O registro do blueprint fica no fim do arquivo, depois de
# ARVORE_QUADROS e das funcoes que o modulo precisa existirem.
# ============================================================
import acessos_v2


# ============================================================
# PERMISSÕES — ponto único de decisão
#
# Uma capacidade é um verbo sobre um recurso: 'crm.lead.editar'.
# O escopo diz sobre quais registros ela vale: tudo, time, proprio.
#
# O catálogo vive aqui, no código, e nunca no banco: assim nenhuma
# capacidade existe sem alguém tê-la implementado.
# ============================================================

CATALOGO = {
    # chave: (grupo, rótulo, descrição, escopos possíveis, sensível)
    'projeto.ver':        ('Operação', 'Ver projetos', 'Abrir os quadros e ver os cards.', ('tudo','quadro','proprio'), False),
    'projeto.editar':     ('Operação', 'Editar projetos', 'Criar, editar e mover cards entre fases.', ('tudo','quadro','proprio'), False),
    'projeto.excluir':    ('Operação', 'Excluir projetos', 'Enviar projeto para a lixeira.', ('tudo','quadro','proprio'), False),
    'projeto.solicitar':  ('Operação', 'Solicitar em outro quadro', 'Abrir demanda para outra área.', (), False),
    'projeto.atribuir':   ('Operação', 'Atribuir responsável', 'Direcionar um card novo para quem executa.', ('tudo', 'quadro'), False),
    'tempo.registrar':    ('Operação', 'Registrar tempo', 'Usar o cronômetro e planejar a agenda.', (), False),
    'tempo.ver':          ('Operação', 'Ver tempo lançado', 'Horas na agenda e no histórico dos projetos.', ('tudo','quadro','proprio'), False),

    'crm.lead.ver':       ('Comercial', 'Ver leads', 'Abrir os três funis e ver os cards.', ('tudo','quadro','proprio'), False),
    'crm.lead.editar':    ('Comercial', 'Editar leads', 'Criar, editar e mover no funil.', ('tudo','quadro','proprio'), False),
    'crm.lead.excluir':   ('Comercial', 'Excluir leads', 'Remover lead do funil.', ('tudo','proprio'), False),
    'crm.valor.ver':      ('Comercial', 'Ver valores', 'Valor estimado no card e projeção de receita. Sem esta permissão o funil funciona normalmente, só sem os números.', (), True),
    'crm.painel.ver':     ('Comercial', 'Painel do funil', 'Indicadores de conversão e tempo por etapa.', ('tudo','quadro','proprio'), False),

    'cliente.ver':        ('Clientes', 'Ver clientes', 'Abrir a carteira de clientes.', ('tudo','proprio'), False),
    'cliente.gerir':      ('Clientes', 'Gerir clientes', 'Cadastrar e editar clientes.', (), False),
    'cliente.portal.gerir':('Clientes', 'Gerir portal do cliente', 'Liberar acesso externo e gerir usuários do cliente.', (), False),

    'okr.ver':            ('OKR', 'Ver OKR', 'Ver a árvore de objetivos e o progresso.', ('tudo','quadro'), False),
    'okr.gerir':          ('OKR', 'Gerir OKR', 'Criar e editar objetivos, resultados-chave e tarefas.', ('tudo','quadro'), False),

    'feed.publicar':      ('Comunicação', 'Publicar no mural', 'Post, evento ou celebração.', (), False),
    'feed.comunicado':    ('Comunicação', 'Publicar comunicado', 'A voz institucional da empresa.', (), False),
    'feed.moderar':       ('Comunicação', 'Moderar o mural', 'Fixar, editar e excluir post de qualquer pessoa.', (), False),
    'comentario.excluir': ('Comunicação', 'Excluir comentários', 'Apagar comentário de outra pessoa.', (), False),

    'dashboard.ver':      ('Análise', 'Ver dashboard', 'Painel geral de projetos e produtividade.', ('tudo','quadro','proprio'), False),
    'dados.exportar':     ('Análise', 'Exportar dados', 'Baixar listagens em planilha. Dado exportado sai do controle da plataforma.', (), True),

    'usuario.gerir':      ('Administração', 'Gerir pessoas', 'Criar e editar pessoas da equipe.', (), True),
    'papel.gerir':        ('Administração', 'Gerir papéis', 'Criar papéis e definir permissões.', (), True),
    'lixeira.ver':        ('Administração', 'Ver lixeira', 'Ver e restaurar itens excluídos.', (), False),
    'lixeira.purgar':     ('Administração', 'Apagar em definitivo', 'Remoção irreversível.', (), True),
    'auditoria.ver':      ('Administração', 'Ver auditoria', 'Registro de quem fez o quê.', (), True),
}

GRUPOS_ORDEM = ['Operação', 'Comercial', 'Clientes', 'OKR', 'Comunicação', 'Análise', 'Administração']

# Quadros de trabalho e áreas da plataforma. Ficam no código porque
# são a lista real de telas que existem — não configuração.
# Lista de quadros para as telas de acesso. Definida aqui porque é
# usada antes de ARVORE_QUADROS existir; a função sincroniza_quadros()
# logo abaixo da árvore substitui esta lista pela versão completa.
# Sem isso, Educação e Tecnologia sumiam da tela de acessos e ninguém
# conseguia liberar esses quadros para ninguém.
QUADROS = []
AREAS = [
    ('agenda',    'Agenda',    'calendar_month', 'Planejamento do dia e cronômetro'),
    ('crm',       'CRM',       'filter_alt',     'Funis de qualificação, fechamento e nutrição'),
    ('clientes',  'Clientes',  'business',       'Carteira de clientes'),
    ('okr',       'OKR',       'target',         'Objetivos e resultados-chave'),
    ('feed',      'Mural',     'campaign',       'Comunicados, eventos e celebrações'),
    ('dashboard', 'Painel',    'insights',       'Indicadores de projetos e produtividade'),
    ('lixeira',   'Lixeira',   'delete',         'Itens excluídos e restauração'),
]
QUADROS_VALIDOS = {q for q, _ in QUADROS}
AREAS_VALIDAS = {a for a, _, _, _ in AREAS}


def caps_da_sessao():
    """Capacidades do usuário logado: {capacidade: escopo}.
    Carregadas no login e guardadas na sessão."""
    return session.get('caps') or {}


def pode(capacidade, alvo=None):
    """Verdadeiro se o usuário tem a capacidade e, havendo alvo, se o
    escopo dele alcança esse alvo.

    Escopos:
      tudo    registros de todo mundo
      quadro  registros dos quadros em que a pessoa atua
      proprio só onde ela é responsável

    `alvo` é um dict do registro. O dono vem de 'responsavel',
    'colaborador' ou 'autor'; o quadro vem de 'area' ou 'funil'.
    """
    esc = caps_da_sessao().get(capacidade)
    if esc is None:
        return False
    if alvo is None:
        return True
    if esc == 'tudo':
        return True

    eu = (session.get('usuario_nome') or '').strip().lower()
    dono = (alvo.get('responsavel') or alvo.get('colaborador')
            or alvo.get('autor') or '').strip().lower()

    if esc == 'quadro':
        # O líder responde pelo quadro inteiro: vê o trabalho de todos
        # que atuam nele. Antes isso dependia de `usuarios.equipe`, um
        # texto livre onde "R&S" e "RS" viravam times diferentes.
        return dono == eu or alvo_no_meu_quadro(alvo)

    if esc == 'time':
        # Escopo legado. Enquanto houver papel gravado com 'time',
        # ele se comporta como 'quadro' em vez de falhar.
        return dono == eu or alvo_no_meu_quadro(alvo)

    return dono == eu


def alvo_no_meu_quadro(alvo):
    """True se o registro pertence a um quadro em que a pessoa atua."""
    meus = quadros_permitidos()
    if not meus:
        return False
    area = alvo.get('area')
    if area:
        for q in meus:
            if QUADRO_AREA.get(q) == area:
                return True
    # Leads não têm área: o funil comercial pertence ao quadro Comercial.
    if alvo.get('funil') and 'comercial' in meus:
        return True
    return False


def filtrar(registros, capacidade):
    """Devolve só os registros que o escopo da capacidade alcança."""
    esc = caps_da_sessao().get(capacidade)
    if esc is None:
        return []
    if esc == 'tudo':
        return registros
    return [r for r in registros if pode(capacidade, r)]


def quadros_permitidos():
    """Quadros de trabalho liberados para esta pessoa."""
    return session.get('quadros') or []


def areas_permitidas():
    """Áreas da plataforma liberadas para esta pessoa."""
    return session.get('areas') or []


def exige(capacidade):
    """Decorador de rota: bloqueia quem não tem a capacidade."""
    def wrapper(fn):
        @wraps(fn)
        def interna(*args, **kwargs):
            if 'usuario_id' not in session:
                return jsonify({"erro": "Nao logado"}), 401
            if not pode(capacidade):
                return jsonify({"status": "erro",
                                "mensagem": "Você não tem permissão para isso."}), 403
            return fn(*args, **kwargs)
        return interna
    return wrapper


def carregar_permissoes(usuario):
    """Monta caps, quadros, telas e alcance na sessao. Chamado no login.

    O QUE MUDOU
    -----------
    Antes as capacidades vinham de `papel_capacidades`, com excecoes por
    pessoa em `usuarios.ajustes`. Agora saem de quatro campos da propria
    pessoa: admin, quadros, alcance e areas.

    As ~200 chamadas `pode(...)` espalhadas pelo app nao mudam. Trocamos
    quem responde a pergunta, nao a pergunta.
    """
    try:
        acessos_v2.aplicar_na_sessao(usuario)
    except Exception as e:
        # Sessao sem capacidade nenhuma e ruim, mas login que explode e
        # pior: a pessoa ao menos entra e ve a tela inicial.
        print("Erro ao carregar permissoes:", e)
        session['caps'] = {}
        session['quadros'] = usuario.get('quadros') or []
        session['areas'] = usuario.get('areas') or []


def registrar(acao, recurso=None, alvo_id=None, detalhe=None):
    """Grava na auditoria. Nunca interrompe a operação principal."""
    try:
        supabase.table("auditoria").insert({
            "usuario": session.get('usuario_nome'),
            "usuario_id": str(session.get('usuario_id', '')),
            "acao": acao,
            "recurso": recurso,
            "alvo_id": str(alvo_id) if alvo_id is not None else None,
            "detalhe": detalhe,
        }).execute()
    except Exception as e:
        print("Aviso: auditoria nao registrada:", e)


# ============================================================
# MODO PARALELO — a ponte entre o modelo antigo e o novo
#
# Durante a migração, cada checagem antiga também consulta o modelo
# novo e registra quando os dois discordam. Quem manda é sempre o
# ANTIGO: o novo só observa. Alguns dias de uso real provam a
# equivalência antes de trocar de verdade.
#
# Quando MODO_PARALELO virar False, o novo passa a mandar.
# ============================================================

MODO_PARALELO = True

# Traduz o que o modelo antigo perguntava para a capacidade equivalente.
MAPA_MODULO_CAP = {
    'clientes':      'cliente.ver',
    'agenda':        'tempo.registrar',
    'planejamento':  'tempo.registrar',
    'dashboard':     'dashboard.ver',
    'okr':           'okr.ver',
    'crm':           'crm.lead.ver',
    'feed':          'feed.publicar',
    'lixeira':       'lixeira.ver',
    'configuracoes': 'papel.gerir',
}


def _comparar(rotulo, antigo, novo, extra=None):
    """Registra divergência entre os dois modelos. Devolve sempre o antigo.

    Só registra quando o usuário já tem papel — sem papel, o modelo novo
    responde vazio por definição e a divergência não significa nada.
    """
    if not MODO_PARALELO or not session.get('caps'):
        return antigo
    if bool(antigo) != bool(novo):
        try:
            supabase.table("auditoria").insert({
                "usuario": session.get('usuario_nome'),
                "usuario_id": str(session.get('usuario_id', '')),
                "acao": "divergencia_permissao",
                "recurso": rotulo,
                "detalhe": {
                    "antigo": bool(antigo),
                    "novo": bool(novo),
                    "nivel": session.get('nivel_acesso'),
                    "papel": session.get('papel_nome'),
                    "extra": extra,
                },
            }).execute()
        except Exception as e:
            print("Aviso: divergencia nao registrada:", e)
    return antigo


@app.context_processor
def injetar_permissoes():
    """Disponibiliza as permissões do usuário em TODOS os templates,
    para a sidebar e telas decidirem o que mostrar."""
    return {
        "perm_modulos": session.get("perm_modulos") or [],
        "tipo_usuario": session.get("tipo_usuario", "interno"),
        "papel_externo": session.get("papel_externo", "visualizador")
    }

# --- HELPERS DE SEGURANÇA ---

def gerar_hash(senha):
    return bcrypt.hashpw(senha.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

def verificar_hash(senha, hash_armazenado):
    try:
        return bcrypt.checkpw(senha.encode('utf-8'), hash_armazenado.encode('utf-8'))
    except Exception:
        return False

def is_admin():
    return session.get('nivel_acesso') == 'admin'

def is_externo():
    return session.get('tipo_usuario') == 'externo'

def is_cliente():
    # Mantido por compatibilidade: externo é o antigo "cliente"
    return is_externo()

def is_personalizado():
    return session.get('nivel_acesso') == 'personalizado'

def eh_visualizador():
    """Externo com papel de visualizador = somente leitura."""
    return is_externo() and session.get('papel_externo', 'visualizador') == 'visualizador'

def pode_editar_projeto(projeto_id=None):
    """Define se o usuário logado pode escrever (timer, editar, criar).
    Visualizador externo: NÃO. Editor externo: SIM (nos projetos dele).
    Internos seguem suas regras normais."""
    if eh_visualizador():
        return False
    # Editor externo: pode, mas só nos projetos liberados pra ele
    if is_externo():
        if projeto_id is None:
            return True
        return str(projeto_id) in set(projetos_visiveis_cliente())
    return True

def get_perm(chave, padrao=None):
    """Lê uma permissão da sessão de forma segura."""
    return session.get(chave, padrao)

def pode_acessar_modulo(modulo):
    """Verifica se o usuário logado pode acessar um módulo.
    admin/gestor: tudo. comum: os módulos marcados (perm_modulos), mas vê todos os dados.
    colaborador (legado): quadros + agenda. personalizado/externo: conforme perm_modulos."""
    nivel = session.get('nivel_acesso')
    if nivel in ('admin', 'gestor'):
        return _comparar('modulo:' + modulo, True,
                         pode(MAPA_MODULO_CAP.get(modulo, '_')), modulo)
    if nivel == 'colaborador':
        # Legado: colaborador acessa quadros e agenda
        return modulo in ('recrutamento', 'rhestrategico', 'geral', 'agenda')
    # comum, personalizado e externo: usam a lista explícita de módulos
    modulos = session.get('perm_modulos') or []
    return _comparar('modulo:' + modulo, modulo in modulos,
                     pode(MAPA_MODULO_CAP.get(modulo, '_')), modulo)

def filtrar_projetos_permitidos(projetos):
    """Recebe lista de projetos (dicts) e devolve só os que o usuário logado pode ver,
    combinando as dimensões de cliente e projeto. Não afeta admin/gestor."""
    nivel = session.get('nivel_acesso')

    # Admin e Gestor veem tudo (comportamento atual preservado)
    if nivel in ('admin', 'gestor'):
        if session.get('caps'):
            novo = filtrar(projetos, 'projeto.ver')
            _comparar('projeto.ver:qtd', len(projetos) == len(projetos),
                      len(novo) == len(projetos),
                      {"antigo": len(projetos), "novo": len(novo)})
        return projetos

    # Comum: vê TODOS os dados (o controle é só de módulos, não de dados)
    if nivel == 'comum':
        return projetos

    # Colaborador (legado): só onde é responsável
    if nivel == 'colaborador':
        meu_nome = (session.get('usuario_nome') or '').strip().lower()
        antigo = [p for p in projetos if (p.get('responsavel') or '').strip().lower() == meu_nome]
        if session.get('caps'):
            novo = filtrar(projetos, 'projeto.ver')
            _comparar('projeto.ver:qtd', True, len(novo) == len(antigo),
                      {"antigo": len(antigo), "novo": len(novo)})
        return antigo

    # === PERSONALIZADO (interno) e EXTERNO (cliente): lógica granular ===
    perm_cli_modo = session.get('perm_clientes_modo') or 'todos'
    perm_cli_ids = set(str(x) for x in (session.get('perm_clientes_ids') or []))
    perm_proj_modo = session.get('perm_projetos_modo') or 'todos'
    perm_proj_ids = set(str(x) for x in (session.get('perm_projetos_ids') or []))
    meu_nome = (session.get('usuario_nome') or '').strip().lower()

    resultado = []
    for p in projetos:
        # Dimensão CLIENTE
        if perm_cli_modo == 'proprios':
            # "seus" = projetos onde ele é responsável
            if (p.get('responsavel') or '').strip().lower() != meu_nome:
                continue
        elif perm_cli_modo == 'selecionados':
            if str(p.get('cliente_id')) not in perm_cli_ids:
                continue
        # 'todos' não filtra por cliente

        # Dimensão PROJETO
        if perm_proj_modo == 'selecionados':
            if str(p.get('id')) not in perm_proj_ids:
                continue
        # 'todos' não filtra por projeto

        # Para EXTERNO: além de tudo, o projeto precisa estar marcado como visível
        if is_externo() and not p.get('visivel_cliente'):
            continue

        resultado.append(p)
    return resultado

def projetos_visiveis_cliente():
    """Compatibilidade: retorna IDs de projetos visíveis para o externo logado."""
    try:
        res = supabase.table("projetos").select("*").execute()
        ativos = [p for p in res.data if not p.get("excluido_em")]
        permitidos = filtrar_projetos_permitidos(ativos)
        return [str(p["id"]) for p in permitidos]
    except Exception:
        return []

# --- LOGIN E SEGURANÇA ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        dados = request.json
        email = dados.get('email')
        senha = dados.get('senha')
        # "Manter conectado" estende a sessão para 7 dias. Sem ele, a sessão
        # dura o navegador aberto. Sete e não trinta: a plataforma guarda
        # dado de cliente e valor comercial.
        session.permanent = bool(dados.get('lembrar'))

        # Busca o usuário só pelo e-mail
        res = supabase.table("usuarios").select("*").eq("email", email).execute()

        if not res.data:
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha inválidos"}), 401

        usuario = res.data[0]
        if usuario.get("ativo") is False:
            # Mesma mensagem do erro de senha: dizer "conta desativada"
            # confirma que o e-mail existe.
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha inválidos"}), 401
        autenticado = False

        # 1. Se já tem hash, valida pelo hash
        if usuario.get("senha_hash"):
            autenticado = verificar_hash(senha, usuario["senha_hash"])
        # 2. Senão, valida pela senha em texto puro (legado) e CONVERTE para hash
        elif usuario.get("senha") is not None and senha == usuario["senha"]:
            autenticado = True
            try:
                novo_hash = gerar_hash(senha)
                # Converte e apaga o texto puro no mesmo movimento: quem
                # entra uma vez deixa de ter a senha legível no banco.
                supabase.table("usuarios").update(
                    {"senha_hash": novo_hash, "senha": None}
                ).eq("id", usuario["id"]).execute()
            except Exception as e:
                print(f"[AVISO] Falha ao converter senha para hash: {str(e)}")

        if autenticado:
            session['usuario_id'] = usuario['id']
            session['usuario_nome'] = usuario['nome']
            session['nivel_acesso'] = usuario.get('nivel_acesso', 'colaborador')
            session['tipo_usuario'] = usuario.get('tipo_usuario', 'interno')
            session['papel_externo'] = usuario.get('papel_externo', 'visualizador')
            session['cliente_vinculado_id'] = usuario.get('cliente_vinculado_id')
            session['perm_modulos'] = usuario.get('perm_modulos') or []
            session['perm_clientes_modo'] = usuario.get('perm_clientes_modo') or 'todos'
            session['perm_clientes_ids'] = usuario.get('perm_clientes_ids') or []
            session['perm_projetos_modo'] = usuario.get('perm_projetos_modo') or 'todos'
            session['perm_projetos_ids'] = usuario.get('perm_projetos_ids') or []
            # Modelo novo: carrega capacidades, quadros e equipe.
            # Sem papel definido devolve vazio, e o sistema segue no modelo
            # antigo — é o que permite migrar sem deslogar ninguém.
            carregar_permissoes(usuario)
            # Último acesso: alimenta o "nunca acessou" do portal do cliente.
            try:
                supabase.table("usuarios").update(
                    {"ultimo_acesso": datetime.now(timezone.utc).isoformat()}
                ).eq("id", usuario["id"]).execute()
            except Exception as e:
                print("Aviso: ultimo_acesso nao registrado:", e)
            return jsonify({"status": "sucesso"}), 200
        else:
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha inválidos"}), 401

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login', proximo=request.path))

# --- ROTAS PROTEGIDAS ---

@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    # Cliente vai direto para a Agenda (portal dele)
    if is_cliente():
        return redirect(url_for('planejamento'))
    return render_template('index.html', usuario=session.get('usuario_nome'), usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

@app.route('/board/<nome_quadro>')
@app.route('/board/<nome_quadro>/<sub>')
def tela_projetos(nome_quadro, sub=None):
    """Abre a família inteira, ou já numa subdivisão.

    /board/rhestrategico      -> abas Todos, Mensalista, PCCS, PCO, GD
    /board/rhestrategico/pccs -> abre direto na aba PCCS
    """
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    # Permissão é da família: quem vê RH Estratégico vê as quatro.
    if (is_personalizado() or is_externo()) and not pode_acessar_modulo(nome_quadro):
        return redirect(url_for('index'))
    # Subdivisão inventada na URL volta para a família, em vez de
    # abrir uma aba que não existe.
    if sub and not sub_valida(nome_quadro, sub):
        return redirect(url_for('tela_projetos', nome_quadro=nome_quadro))
    return render_template('projetos.html',
                           quadro_atual=nome_quadro,
                           sub_atual=sub or '',
                           usuario_nome=session.get('usuario_nome'),
                           nivel_acesso=session.get('nivel_acesso', 'colaborador'))


@app.route('/api/quadros/arvore', methods=['GET'])
def arvore_quadros():
    """A árvore de quadros, filtrada pelo que a pessoa pode ver."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    permitidos = quadros_permitidos()
    tudo = session.get('nivel_acesso') in ('admin', 'gestor') and not is_personalizado()
    saida = []
    for chave, area, produto, icone, subs in ARVORE_QUADROS:
        if not tudo and permitidos and chave not in permitidos:
            continue
        saida.append({
            "chave": chave, "area": area, "produto": produto, "icone": icone,
            "subs": [{"chave": s[0], "nome": s[1], "descricao": s[2]} for s in subs],
        })
    return jsonify({"status": "sucesso", "quadros": saida}), 200

# --- API PROJETOS ---

@app.route('/api/projetos', methods=['GET'])
def listar_projetos():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res_projetos = supabase.table("projetos").select("*").execute()
        projetos = [p for p in res_projetos.data if not p.get("excluido_em")]

        # CONTROLE DE ACESSO: função central que cobre todos os níveis
        projetos = filtrar_projetos_permitidos(projetos)
        
        # 1. Busca os tempos agregados (via VIEW = 1 query só, muito mais rápido)
        tempos_agrupados = {}
        try:
            res_tempo = supabase.table("vw_tempo_por_projeto").select("projeto_id, total_segundos").execute()
            for row in res_tempo.data:
                tempos_agrupados[str(row['projeto_id'])] = row['total_segundos'] or 0
        except Exception as erro_view:
            # FALLBACK: se a view ainda não existir, usa o método antigo (paginação)
            print(f"[AVISO] View indisponível, usando fallback: {str(erro_view)}")
            page_size = 1000
            offset = 0
            while True:
                res_tempo = supabase.table("time_logs").select("projeto_id, tempo_segundos").range(offset, offset + page_size - 1).execute()
                if not res_tempo.data:
                    break
                for log in res_tempo.data:
                    pid = str(log['projeto_id'])
                    tempos_agrupados[pid] = tempos_agrupados.get(pid, 0) + (log['tempo_segundos'] or 0)
                if len(res_tempo.data) < page_size:
                    break
                offset += page_size
            
        # 2. Busca notificações não lidas
        res_unread = supabase.table("comentarios").select("projeto_id").eq("lido_pelo_responsavel", False).execute()
        unread_counts = {}
        for c in res_unread.data:
            # BLINDAGEM: Força o ID a ser string
            pid = str(c['projeto_id'])
            unread_counts[pid] = unread_counts.get(pid, 0) + 1
            
        # 3. Consolida os dados nos projetos
        for p in projetos:
            pid_str = str(p['id']) # Garante que está buscando a string correta
            p['tempo_total_segundos'] = tempos_agrupados.get(pid_str, 0)
            p['qtd_nao_lidos'] = unread_counts.get(pid_str, 0)
            
        return jsonify({"status": "sucesso", "projetos": projetos}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no GET Projetos: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar projetos."}), 500

@app.route('/api/projetos', methods=['POST'])
def criar_projeto():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if is_externo(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        novo_projeto = {
            "empresa": dados.get("empresa"),
            "cliente_id": dados.get("cliente_id"),
            "nome_projeto": dados.get("nome_projeto"),
            "area": dados.get("area", "Geral"),
            "responsavel": dados.get("responsavel", "Não definido"),
            "status": dados.get("status_inicial", "Backlog"),
            "progresso": 0,
            "anotacoes": "",
            "prazo_data": dados.get("prazo_data") if dados.get("prazo_data") else None,
            "is_scrum": bool(dados.get("is_scrum", False))
        }
        supabase.table("projetos").insert(novo_projeto).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no POST Projetos: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao criar o projeto."}), 500

@app.route('/api/projetos/<projeto_id>', methods=['PUT'])
def atualizar_projeto(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_editar_projeto(projeto_id): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        atualizacao = {}
        res_atual = (supabase.table("projetos")
                     .select("status", "data_inicio", "data_conclusao", "area",
                             "nome_projeto", "empresa", "cliente_id", "origem_lead_id")
                     .eq("id", projeto_id).execute())
        status_anterior = res_atual.data[0].get("status") if res_atual.data else None
        
        if "status" in dados:
            novo_status = dados.get("status")
            atualizacao["status"] = novo_status
            atualizacao["data_status_atual"] = agora_br()

            status_pausa = ["Backlog", "Não Iniciado", "Pausado", "Finalizado", "Onboarding", "Cancelado"]
            # data_conclusao só deve marcar finalização REAL (Finalizado/Cancelado),
            # não pausas — senão a data do comissionamento fica incorreta.
            if novo_status in ["Finalizado", "Cancelado"]:
                # só grava se ainda não tem (preserva a data da 1ª finalização)
                if not (res_atual.data and res_atual.data[0].get("data_conclusao")):
                    atualizacao["data_conclusao"] = agora_br()
            elif novo_status not in status_pausa:
                # voltou a um status ativo → limpa a conclusão
                atualizacao["data_conclusao"] = None

            if res_atual.data and not res_atual.data[0].get("data_inicio"):
                atualizacao["data_inicio"] = agora_br()

            # Trilha de fases: alimenta o gráfico de gargalo do painel.
            # Falha aqui não pode impedir o card de mover.
            if novo_status and novo_status != status_anterior:
                try:
                    if novo_status == 'Finalizado':
                        # O que acontece ao finalizar é escolha de quem finaliza:
                        # nem toda entrega gera cobrança, e nem todo produto
                        # entra em relacionamento. A tela pergunta, e o que vier
                        # marcado chega aqui em `encerramento`.
                        p = res_atual.data[0] if res_atual.data else {}
                        enc = d.get("encerramento") or {}
                        disparar('projeto.finalizado', {
                            "projeto_id": projeto_id,
                            "projeto_nome": p.get("nome_projeto"),
                            "area": p.get("area"),
                            "cliente_id": p.get("cliente_id"),
                            "cliente_nome": p.get("empresa"),
                            "lead_id": p.get("origem_lead_id"),
                            "quadro": next((q for q, a2 in QUADRO_AREA.items()
                                            if a2 == p.get("area")), None),
                            "com_relacionamento": bool(enc.get("relacionamento")),
                            "com_cobranca": bool(enc.get("cobranca")),
                            "valor": enc.get("valor"),
                        })
                except Exception as e_fluxo:
                    print("Aviso: fluxo de finalizacao nao rodou:", e_fluxo)

                try:
                    supabase.table("projeto_movimentos").insert({
                        "projeto_id": projeto_id,
                        "de_status": status_anterior,
                        "para_status": novo_status,
                        "area": (res_atual.data[0].get("area") if res_atual.data else None),
                        "autor": session.get('usuario_nome'),
                    }).execute()
                except Exception as e_mov:
                    print("Aviso: movimento de projeto nao registrado:", e_mov)

            if novo_status and novo_status != status_anterior:
                try:
                    supabase.table("historico_colunas").insert({
                        "projeto_id": projeto_id,
                        "status_anterior": status_anterior,
                        "status_novo": novo_status,
                        "movimentado_por": session.get("usuario_nome", "Sistema")
                    }).execute()
                except Exception as erro_hist:
                    print(f"[AVISO BI] Erro ao gravar histórico: {str(erro_hist)}")

        if "area" in dados: atualizacao["area"] = dados.get("area")
        if "responsavel" in dados: atualizacao["responsavel"] = dados.get("responsavel")
        if "empresa" in dados: atualizacao["empresa"] = dados.get("empresa")
        if "cliente_id" in dados: atualizacao["cliente_id"] = dados.get("cliente_id")
        if "nome_projeto" in dados: atualizacao["nome_projeto"] = dados.get("nome_projeto")
        if "prazo_data" in dados: atualizacao["prazo_data"] = dados.get("prazo_data") if dados.get("prazo_data") else None
        if "is_scrum" in dados: atualizacao["is_scrum"] = bool(dados.get("is_scrum"))
        if "visivel_cliente" in dados: atualizacao["visivel_cliente"] = bool(dados.get("visivel_cliente"))
        
        # --- GRAVAÇÃO DAS ANOTAÇÕES ---
        if "anotacoes" in dados: atualizacao["anotacoes"] = dados.get("anotacoes")
        
        supabase.table("projetos").update(atualizacao).eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no PUT (Atualizar): {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro interno de atualização"}), 500

@app.route('/api/projetos/<projeto_id>', methods=['DELETE'])
def excluir_projeto(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if is_externo(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        # SOFT DELETE: marca como excluído em vez de apagar (vai para a lixeira)
        supabase.table("projetos").update({
            "excluido_em": datetime.now(timezone.utc).isoformat(),
            "excluido_por": session.get('usuario_nome'),
        }).eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir o projeto."}), 500


# --- LIXEIRA (somente admin) ---

@app.route('/lixeira')
def lixeira_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    if not pode_ver_lixeira():
        return redirect(url_for('index'))
    return render_template('lixeira.html',
                           usuario_nome=session.get('usuario_nome'),
                           nivel_acesso=session.get('nivel_acesso'),
                           tipo_usuario=session.get('tipo_usuario', 'interno'),
                           papel_externo=session.get('papel_externo', ''),
                           perm_modulos=session.get('perm_modulos', []))

@app.route('/api/lixeira', methods=['GET'])
def listar_lixeira():
    """Tudo que foi excluído: projetos, clientes e leads.

    Leads estavam de fora — a exclusão do CRM já gravava
    `excluido_em`, mas a lixeira nunca olhava para lá, então todo
    lead excluído ficava invisível para sempre.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_lixeira():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        itens = []

        proj = (supabase.table("projetos").select("*")
                .not_.is_("excluido_em", "null").execute()).data or []
        # Horas por projeto, para dizer o que se perde antes de apagar.
        horas = {}
        if proj:
            try:
                r = (supabase.table("time_logs")
                     .select("projeto_id, tempo_segundos")
                     .in_("projeto_id", [str(p["id"]) for p in proj]).execute())
                for l in (r.data or []):
                    pid = str(l.get("projeto_id"))
                    horas[pid] = horas.get(pid, 0) + (l.get("tempo_segundos") or 0)
            except Exception as e:
                print("Aviso: horas da lixeira indisponiveis:", e)
        for p in proj:
            itens.append({
                "id": p["id"], "tipo": "projeto",
                "nome": p.get("nome_projeto"),
                "detalhe": p.get("empresa") or "sem cliente",
                "area": p.get("area"),
                "status": p.get("status"),
                "horas": round(horas.get(str(p["id"]), 0) / 3600.0),
                "excluido_em": p.get("excluido_em"),
                "excluido_por": p.get("excluido_por"),
            })

        cli = (supabase.table("clientes").select("*")
               .not_.is_("excluido_em", "null").execute()).data or []
        # Projetos que ficaram na lixeira junto com o cliente.
        for c in cli:
            juntos = sum(1 for p in proj if str(p.get("cliente_id")) == str(c["id"]))
            itens.append({
                "id": c["id"], "tipo": "cliente",
                "nome": c.get("nome_empresa"),
                "detalhe": c.get("cidade") or "sem cidade",
                "area": None, "status": None,
                "projetos_juntos": juntos,
                "excluido_em": c.get("excluido_em"),
                "excluido_por": c.get("excluido_por"),
            })

        try:
            leads = (supabase.table("leads").select("*")
                     .not_.is_("excluido_em", "null").execute()).data or []
            for l in leads:
                itens.append({
                    "id": l["id"], "tipo": "lead",
                    "nome": l.get("lead") or l.get("empresa") or "lead sem nome",
                    "detalhe": (l.get("empresa") or "") + (
                        " · " + str(l.get("coluna")) if l.get("coluna") else ""),
                    "area": "CRM", "status": l.get("coluna"),
                    "funil": l.get("funil"),
                    "valor": l.get("valor_estimado"),
                    "excluido_em": l.get("excluido_em"),
                    "excluido_por": l.get("excluido_por"),
                })
        except Exception as e:
            print("Aviso: leads da lixeira indisponiveis:", e)

        itens.sort(key=lambda x: str(x.get("excluido_em") or ""), reverse=True)
        return jsonify({
            "status": "sucesso",
            "itens": itens,
            "pode_purgar": pode('lixeira.purgar') or is_admin(),
        }), 200
    except Exception as e:
        print("Erro na lixeira:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar a lixeira.",
                        "detalhe": str(e)[:300]}), 500


TABELA_DO_TIPO = {"projeto": "projetos", "cliente": "clientes", "lead": "leads"}


@app.route('/api/lixeira/<tipo>/<item_id>/restaurar', methods=['PUT'])
def restaurar_item(tipo, item_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_lixeira():
        return jsonify({"erro": "Acesso negado"}), 403
    tabela = TABELA_DO_TIPO.get(tipo)
    if not tabela:
        return jsonify({"status": "erro", "mensagem": "Tipo inválido."}), 400
    try:
        aviso = None
        if tipo == "projeto":
            # A fase pode ter deixado de existir enquanto o card estava
            # na lixeira. Nesse caso volta para o Backlog, avisando.
            r = (supabase.table("projetos").select("status, area")
                 .eq("id", item_id).limit(1).execute())
            if r.data:
                st = r.data[0].get("status")
                if st in ('Não Iniciado', 'Kick-off') and st != FASE_ENTRADA:
                    supabase.table("projetos").update(
                        {"status": FASE_ENTRADA}).eq("id", item_id).execute()
                    aviso = f"A fase '{st}' não existe mais; o projeto voltou para {FASE_ENTRADA}."

        supabase.table(tabela).update(
            {"excluido_em": None, "excluido_por": None}).eq("id", item_id).execute()
        registrar_auditoria('item_restaurado', tipo, item_id, {})
        return jsonify({"status": "sucesso", "aviso": aviso}), 200
    except Exception as e:
        print("Erro ao restaurar:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao restaurar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/lixeira/<tipo>/<item_id>/definitivo', methods=['DELETE'])
def excluir_definitivo(tipo, item_id):
    """Apaga do banco. Não tem volta.

    Exige `lixeira.purgar`, que é capacidade sensível: quem tem
    apenas `lixeira.ver` restaura, mas não apaga.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not (pode('lixeira.purgar') or is_admin()):
        return jsonify({"status": "erro",
                        "mensagem": "Só quem administra pode apagar em definitivo."}), 403
    tabela = TABELA_DO_TIPO.get(tipo)
    if not tabela:
        return jsonify({"status": "erro", "mensagem": "Tipo inválido."}), 400
    try:
        # Guarda o nome antes de apagar: depois não há como saber
        # o que foi removido.
        campo = {"projetos": "nome_projeto", "clientes": "nome_empresa", "leads": "lead"}[tabela]
        r = supabase.table(tabela).select(campo).eq("id", item_id).limit(1).execute()
        nome = (r.data or [{}])[0].get(campo)

        supabase.table(tabela).delete().eq("id", item_id).execute()
        registrar_auditoria('item_purgado', tipo, item_id, {"nome": nome})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro ao excluir em definitivo:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/lixeira/lote', methods=['POST'])
def lixeira_lote():
    """Restaura ou apaga vários itens de uma vez.

    Cada item é tratado isolado: um que falhe não impede os outros,
    e a resposta diz quantos deram certo.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_lixeira():
        return jsonify({"erro": "Acesso negado"}), 403
    d = request.json or {}
    acao = d.get("acao")
    itens = d.get("itens") or []
    if acao not in ("restaurar", "purgar"):
        return jsonify({"status": "erro", "mensagem": "Ação inválida."}), 400
    if acao == "purgar" and not (pode('lixeira.purgar') or is_admin()):
        return jsonify({"status": "erro",
                        "mensagem": "Só quem administra pode apagar em definitivo."}), 403
    if len(itens) > 100:
        return jsonify({"status": "erro", "mensagem": "Máximo de 100 itens por vez."}), 400

    ok, falhas = 0, []
    for it in itens:
        tabela = TABELA_DO_TIPO.get(it.get("tipo"))
        item_id = it.get("id")
        if not tabela or not item_id:
            falhas.append(it.get("nome") or "item")
            continue
        try:
            if acao == "restaurar":
                supabase.table(tabela).update(
                    {"excluido_em": None, "excluido_por": None}).eq("id", item_id).execute()
            else:
                supabase.table(tabela).delete().eq("id", item_id).execute()
            ok += 1
        except Exception as e:
            print(f"Erro no lote ({acao} {tabela} {item_id}):", e)
            falhas.append(it.get("nome") or str(item_id))

    registrar_auditoria(
        'lote_restaurado' if acao == 'restaurar' else 'lote_purgado',
        'lixeira', None, {"quantidade": ok, "falhas": len(falhas)})
    return jsonify({"status": "sucesso", "feitos": ok, "falhas": falhas}), 200


# --- API TIMER ---

@app.route('/api/projetos/<projeto_id>/timer', methods=['POST'])
def salvar_tempo(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_editar_projeto(projeto_id): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        novo_log = {
            "projeto_id": projeto_id,
            "colaborador": dados.get("colaborador", "Membro"), 
            "descricao_tarefa": dados.get("descricao_tarefa", "Atividade"),
            "tempo_segundos": int(dados.get("tempo_segundos", 0)),
            "data_inicio_atividade": dados.get("data_inicio_atividade"),
            "data_fim_atividade": dados.get("data_fim_atividade"),
            # Preenchido quando o timer parte da Agenda; nulo quando parte do quadro.
            # É o que separa "planejado e realizado" de "feito fora do plano".
            "planejamento_id": dados.get("planejamento_id")
        }
        supabase.table("time_logs").insert(novo_log).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        try:
            log_seguro = {
                "projeto_id": projeto_id,
                "colaborador": dados.get("colaborador", "Membro"), 
                "descricao_tarefa": dados.get("descricao_tarefa", "Atividade"),
                "tempo_segundos": int(dados.get("tempo_segundos", 0))
            }
            supabase.table("time_logs").insert(log_seguro).execute()
            return jsonify({"status": "sucesso", "alerta": "Salvo sem datas"}), 200
        except Exception as erro_critico:
            return jsonify({"status": "erro", "mensagem": "Erro ao salvar log de tempo"}), 500

@app.route('/api/projetos/<projeto_id>/historico', methods=['GET'])
def historico_tempo(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        resposta = supabase.table("time_logs").select("*").eq("projeto_id", projeto_id).order("criado_em", desc=True).execute()
        return jsonify({"status": "sucesso", "historico": resposta.data}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar histórico."}), 500

# --- API COMENTÁRIOS E NOTIFICAÇÕES ---

@app.route('/api/notificacoes', methods=['GET'])
def get_notificacoes():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    usuario = session.get('usuario_nome')
    try:
        # 1. Busca todos os projetos do banco
        res_projetos = supabase.table('projetos').select('id, nome_projeto, responsavel').execute()
        projetos_do_usuario = {}
        
        # Filtra na unha (Python) para evitar erro de maiúscula/minúscula/espaço
        for p in res_projetos.data:
            if p['responsavel'] and p['responsavel'].strip().lower() == usuario.strip().lower():
                projetos_do_usuario[p['id']] = p['nome_projeto']

        if not projetos_do_usuario:
            return jsonify({"status": "sucesso", "notificacoes": []}), 200

        proj_ids = list(projetos_do_usuario.keys())
        
        # 2. Busca comentários não lidos apenas desses projetos
        res_comentarios = supabase.table('comentarios').select('*').in_('projeto_id', proj_ids).eq('lido_pelo_responsavel', False).execute()
        
        notificacoes = []
        for c in res_comentarios.data:
            # Não notifica se o autor for você mesmo
            if c['autor'].strip().lower() != usuario.strip().lower():
                c['nome_projeto'] = projetos_do_usuario[c['projeto_id']]
                notificacoes.append(c)

        # 3. Ordena para os mais novos ficarem no topo
        notificacoes.sort(key=lambda x: x['criado_em'], reverse=True)
        
        return jsonify({"status": "sucesso", "notificacoes": notificacoes}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro em Notificacoes: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao buscar notificacoes"}), 500


@app.route('/api/projetos/<projeto_id>/comentarios', methods=['GET'])
def listar_comentarios(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res = supabase.table("comentarios").select("*").eq("projeto_id", projeto_id).order("criado_em", desc=False).execute()
        return jsonify({"status": "sucesso", "comentarios": res.data}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar comentários."}), 500

@app.route('/api/projetos/<projeto_id>/comentarios', methods=['POST'])
def adicionar_comentario(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    # Cliente só pode comentar em projeto liberado para ele
    if is_cliente() and str(projeto_id) not in set(projetos_visiveis_cliente()):
        return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    texto = dados.get("texto")
    parent_id = dados.get("parent_id", None)
    
    if not texto: return jsonify({"erro": "Texto vazio"}), 400
    try:
        autor = session.get("usuario_nome", "Usuário")
        
        res_proj = supabase.table("projetos").select("responsavel").eq("id", projeto_id).execute()
        responsavel_projeto = res_proj.data[0]['responsavel'] if res_proj.data else ""
        
        ja_lido = True if autor.strip().lower() == responsavel_projeto.strip().lower() else False
        
        novo_comentario = {
            "projeto_id": projeto_id,
            "autor": autor,
            "texto": texto,
            "parent_id": parent_id,
            "lido_pelo_responsavel": ja_lido
        }
        supabase.table("comentarios").insert(novo_comentario).execute()
        
        # Baixa Automática!
        if autor.strip().lower() == responsavel_projeto.strip().lower():
            supabase.table("comentarios").update({"lido_pelo_responsavel": True}).eq("projeto_id", projeto_id).eq("lido_pelo_responsavel", False).execute()
            
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar comentário."}), 500

@app.route('/api/comentarios/<comentario_id>', methods=['PUT'])
def editar_comentario(comentario_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    texto_novo = dados.get("texto")
    if not texto_novo: return jsonify({"erro": "Texto vazio"}), 400
    try:
        supabase.table("comentarios").update({"texto": texto_novo}).eq("id", comentario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao editar comentário."}), 500

@app.route('/api/comentarios/<comentario_id>/lido', methods=['PUT'])
def marcar_comentario_lido(comentario_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        supabase.table("comentarios").update({"lido_pelo_responsavel": True}).eq("id", comentario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao marcar como lido."}), 500

# --- CONFIGURAÇÕES / USUÁRIOS (somente admin) ---

@app.route('/api/usuarios', methods=['GET'])
def listar_usuarios():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        res = supabase.table("usuarios").select("id, nome, email, cargo, nivel_acesso, tipo_usuario, papel_externo, cliente_vinculado_id, perm_modulos, perm_clientes_modo, perm_clientes_ids, perm_projetos_modo, perm_projetos_ids, criado_em").order("nome", desc=False).execute()
        return jsonify({"status": "sucesso", "usuarios": res.data}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no GET Usuarios: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar usuários."}), 500

def montar_permissoes(dados):
    """Monta o dict de campos de permissão a salvar, conforme o nível/tipo.
    Para nível admin limpa as permissões (vê tudo)."""
    nivel = dados.get("nivel_acesso", "comum")
    tipo = dados.get("tipo_usuario", "interno")
    perms = {}

    # Comum/Personalizado (interno) OU qualquer externo: usa a lista de módulos
    if nivel in ("comum", "personalizado") or tipo == "externo":
        perms["perm_modulos"] = dados.get("perm_modulos", [])
        perms["perm_clientes_modo"] = dados.get("perm_clientes_modo", "todos")
        perms["perm_clientes_ids"] = dados.get("perm_clientes_ids", [])
        perms["perm_projetos_modo"] = dados.get("perm_projetos_modo", "todos")
        perms["perm_projetos_ids"] = dados.get("perm_projetos_ids", [])
        perms["cliente_vinculado_id"] = dados.get("cliente_vinculado_id")
        if tipo == "externo":
            perms["papel_externo"] = dados.get("papel_externo", "visualizador")
    else:
        # Admin (e gestor legado): vê tudo, sem restrição de módulo
        perms["perm_modulos"] = []
        perms["perm_clientes_modo"] = "todos"
        perms["perm_clientes_ids"] = []
        perms["perm_projetos_modo"] = "todos"
        perms["perm_projetos_ids"] = []
        perms["cliente_vinculado_id"] = None
    return perms

@app.route('/api/usuarios', methods=['POST'])
def criar_usuario():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        senha_texto = dados.get("senha")
        if not senha_texto:
            return jsonify({"status": "erro", "mensagem": "Senha é obrigatória."}), 400

        novo = {
            "nome": dados.get("nome"),
            "email": dados.get("email"),
            "cargo": dados.get("cargo"),
            "nivel_acesso": dados.get("nivel_acesso", "colaborador"),
            "tipo_usuario": dados.get("tipo_usuario", "interno"),
            # Só o hash é gravado. A coluna `senha` em texto puro é legado
            # e deixa de receber valor a partir daqui.
            "senha_hash": gerar_hash(senha_texto)
        }
        # Permissões granulares (nível personalizado ou usuário externo)
        novo.update(montar_permissoes(dados))
        supabase.table("usuarios").insert(novo).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no POST Usuario: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/usuarios/<usuario_id>', methods=['PUT'])
def atualizar_usuario(usuario_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        atualizacao = {}
        if "nome" in dados: atualizacao["nome"] = dados["nome"]
        if "email" in dados: atualizacao["email"] = dados["email"]
        if "cargo" in dados: atualizacao["cargo"] = dados["cargo"]
        if "nivel_acesso" in dados: atualizacao["nivel_acesso"] = dados["nivel_acesso"]
        if "tipo_usuario" in dados: atualizacao["tipo_usuario"] = dados["tipo_usuario"]
        # Permissões granulares
        atualizacao.update(montar_permissoes(dados))
        # Se enviou nova senha, atualiza texto + hash
        if dados.get("senha"):
            # Ao trocar a senha, o texto puro antigo é apagado de vez.
            atualizacao["senha"] = None
            atualizacao["senha_hash"] = gerar_hash(dados["senha"])

        supabase.table("usuarios").update(atualizacao).eq("id", usuario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no PUT Usuario: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/usuarios/<usuario_id>', methods=['DELETE'])
def excluir_usuario(usuario_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    # Impede o admin de excluir a si mesmo
    if str(usuario_id) == str(session.get('usuario_id')):
        return jsonify({"status": "erro", "mensagem": "Você não pode excluir seu próprio usuário."}), 400
    try:
        supabase.table("usuarios").delete().eq("id", usuario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/usuarios/gerar-senha', methods=['GET'])
def gerar_senha_aleatoria():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    alfabeto = string.ascii_letters + string.digits
    senha = ''.join(secrets.choice(alfabeto) for _ in range(10))
    return jsonify({"senha": senha}), 200

@app.route('/api/projetos-para-selecao', methods=['GET'])
def projetos_para_selecao():
    """Lista enxuta de projetos ativos (id, nome, cliente, área) para os
    seletores de permissão na tela de usuários. Apenas admin."""
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        res = supabase.table("projetos").select("id, nome_projeto, empresa, area, cliente_id, excluido_em").execute()
        projetos = [
            {"id": str(p["id"]), "nome": p.get("nome_projeto"), "empresa": p.get("empresa"), "area": p.get("area"), "cliente_id": str(p.get("cliente_id"))}
            for p in res.data if not p.get("excluido_em")
        ]
        projetos.sort(key=lambda x: (x.get("empresa") or "", x.get("nome") or ""))
        return jsonify({"status": "sucesso", "projetos": projetos}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# --- USUÁRIOS EXTERNOS (somente admin) ---







# --- CLIENTES ---

@app.route('/clientes')
def clientes_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    if is_externo():
        return redirect(url_for('planejamento'))
    if is_personalizado() and not pode_acessar_modulo('clientes'):
        return redirect(url_for('index'))
    return render_template('clientes.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

@app.route('/api/clientes', methods=['GET'])
def listar_clientes():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res = supabase.table("clientes").select("*").order("nome_empresa", desc=False).execute()
        clientes = [c for c in res.data if not c.get("excluido_em")]

        # Conta projetos por cliente (para a listagem)
        res_proj = supabase.table("projetos").select("cliente_id, status, area, responsavel, excluido_em").execute()
        contagem = {}
        for p in res_proj.data:
            if p.get("excluido_em"): continue
            cid = p.get("cliente_id")
            if not cid: continue
            cid = str(cid)
            if cid not in contagem:
                contagem[cid] = {"total": 0, "ativos": 0, "areas": set(), "responsaveis": set()}
            contagem[cid]["total"] += 1
            if p.get("status") not in ["Finalizado", "Cancelado"]:
                contagem[cid]["ativos"] += 1
            if p.get("area"): contagem[cid]["areas"].add(p["area"])
            if p.get("responsavel"): contagem[cid]["responsaveis"].add(p["responsavel"])

        for c in clientes:
            cid = str(c["id"])
            dados_c = contagem.get(cid, {})
            c["qtd_projetos"] = dados_c.get("total", 0)
            c["qtd_ativos"] = dados_c.get("ativos", 0)
            c["areas"] = sorted(list(dados_c.get("areas", set())))
            c["responsaveis"] = sorted(list(dados_c.get("responsaveis", set())))

        return jsonify({"status": "sucesso", "clientes": clientes}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no GET Clientes: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar clientes."}), 500

@app.route('/api/clientes', methods=['POST'])
def criar_cliente():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    try:
        novo = {
            "nome_empresa": dados.get("nome_empresa"),
            "responsavel": dados.get("responsavel"),
            "observacoes": dados.get("observacoes"),
            "cnpj": dados.get("cnpj"),
            "cidade": dados.get("cidade"),
            "estado": dados.get("estado"),
            "telefone": dados.get("telefone"),
            "email": dados.get("email")
        }
        res = supabase.table("clientes").insert(novo).execute()
        return jsonify({"status": "sucesso", "cliente": res.data[0] if res.data else None}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no POST Cliente: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/clientes/<cliente_id>', methods=['PUT'])
def atualizar_cliente(cliente_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    try:
        atualizacao = {}
        for campo in ["nome_empresa", "cnpj", "cidade", "estado", "telefone", "email"]:
            if campo in dados:
                atualizacao[campo] = dados[campo]

        supabase.table("clientes").update(atualizacao).eq("id", cliente_id).execute()

        # Se mudou o nome, sincroniza o campo legado "empresa" nos projetos
        if "nome_empresa" in atualizacao:
            supabase.table("projetos").update({"empresa": atualizacao["nome_empresa"]}).eq("cliente_id", cliente_id).execute()

        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no PUT Cliente: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/clientes/<cliente_id>', methods=['DELETE'])
def excluir_cliente(cliente_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        # Não deixa excluir se houver projetos ATIVOS vinculados
        res_proj = supabase.table("projetos").select("id, excluido_em").eq("cliente_id", cliente_id).execute()
        ativos = [p for p in res_proj.data if not p.get("excluido_em")]
        if ativos and len(ativos) > 0:
            return jsonify({"status": "erro", "mensagem": f"Cliente tem {len(ativos)} projeto(s) vinculado(s). Não pode ser excluído."}), 400

        # SOFT DELETE: vai para a lixeira
        supabase.table("clientes").update({
            "excluido_em": datetime.now(timezone.utc).isoformat(),
            "excluido_por": session.get('usuario_nome'),
        }).eq("id", cliente_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/clientes/carteira', methods=['GET'])
def carteira_clientes():
    """Clientes com os números que a tela precisa, agrupados por situação.

    Tudo é calculado aqui: a tela recebe pronto, e o escopo de permissão
    é aplicado antes de qualquer dado sair do servidor.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        dias_parado = 60
        try:
            dias_parado = max(15, min(int(request.args.get('parado', 60)), 365))
        except (TypeError, ValueError):
            pass
        hoje = datetime.now(timezone.utc).date().isoformat()
        corte = (datetime.now(timezone.utc) - timedelta(days=dias_parado)).isoformat()
        mes = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        clientes = (supabase.table("clientes").select("*")
                    .order("nome_empresa").execute()).data or []
        todos_proj = (supabase.table("projetos").select("*")
                      .is_("excluido_em", "null").execute()).data or []
        projetos = filtrar_projetos_permitidos(todos_proj)

        # Horas por projeto, do mês e do total.
        horas_mes, horas_total = {}, {}
        try:
            ids = [str(p["id"]) for p in projetos]
            if ids:
                passo, inicio = 1000, 0
                while True:
                    r = (supabase.table("time_logs")
                         .select("projeto_id, tempo_segundos, criado_em")
                         .in_("projeto_id", ids).range(inicio, inicio + passo - 1).execute())
                    if not r.data:
                        break
                    for l in r.data:
                        pid = str(l.get("projeto_id"))
                        seg = l.get("tempo_segundos") or 0
                        horas_total[pid] = horas_total.get(pid, 0) + seg
                        if str(l.get("criado_em") or '') >= mes:
                            horas_mes[pid] = horas_mes.get(pid, 0) + seg
                    if len(r.data) < passo:
                        break
                    inicio += passo
        except Exception as e:
            print("Aviso: time_logs indisponivel na carteira:", e)

        # Quem tem acesso ao portal, por cliente.
        portal = {}
        try:
            ext = (supabase.table("usuarios")
                   .select("cliente_vinculado_id, ativo")
                   .eq("tipo_usuario", "externo").execute()).data or []
            for u in ext:
                cid = str(u.get("cliente_vinculado_id") or '')
                if cid and u.get("ativo") is not False:
                    portal[cid] = portal.get(cid, 0) + 1
        except Exception as e:
            print("Aviso: usuarios externos indisponiveis:", e)

        por_cliente = {}
        for p in projetos:
            cid = str(p.get("cliente_id") or '')
            if cid:
                por_cliente.setdefault(cid, []).append(p)

        saida = []
        for c in clientes:
            cid = str(c["id"])
            meus = por_cliente.get(cid, [])
            ativos = [p for p in meus if p.get("status") not in STATUS_ENCERRADOS]
            concluidos = [p for p in meus if p.get("status") == "Finalizado"]

            atrasados, prazo_prox = 0, None
            for p in ativos:
                prazo = str(p.get("prazo_data") or '')[:10]
                if not prazo:
                    continue
                if prazo < hoje:
                    atrasados += 1
                if prazo_prox is None or prazo < prazo_prox:
                    prazo_prox = prazo

            hm = sum(horas_mes.get(str(p["id"]), 0) for p in meus) / 3600.0
            ht = sum(horas_total.get(str(p["id"]), 0) for p in meus) / 3600.0

            # Última atividade: a mudança de fase mais recente entre os projetos.
            ultima = None
            for p in meus:
                for campo in ("data_status_atual", "atualizado_em", "criado_em"):
                    v = p.get(campo)
                    if v and (ultima is None or str(v) > ultima):
                        ultima = str(v)
                        break

            if c.get("ativo") is False:
                situacao = "encerrado"
            elif atrasados:
                situacao = "atraso"
            elif ativos:
                situacao = "em_dia"
            elif ultima and ultima >= corte:
                situacao = "em_dia"
            else:
                situacao = "parado"

            saida.append({
                "id": c["id"],
                "nome": c.get("nome_empresa"),
                "cnpj": c.get("cnpj"),
                "cidade": c.get("cidade"),
                "estado": c.get("estado"),
                "email": c.get("email"),
                "telefone": c.get("telefone"),
                "responsavel": c.get("responsavel"),
                "criado_em": c.get("criado_em"),
                "ativo": c.get("ativo") is not False,
                "situacao": situacao,
                "projetos_ativos": len(ativos),
                "projetos_concluidos": len(concluidos),
                "atrasados": atrasados,
                "prazo_proximo": prazo_prox,
                "horas_mes": round(hm),
                "horas_total": round(ht),
                "portal": portal.get(cid, 0),
                "dias_parado": _dias_desde(ultima) if ultima else None,
                "areas": sorted({p.get("area") for p in ativos if p.get("area")}),
            })

        resumo = {
            "total": len(saida),
            "com_trabalho": sum(1 for c in saida if c["projetos_ativos"]),
            "com_atraso": sum(1 for c in saida if c["situacao"] == "atraso"),
            "parados": sum(1 for c in saida if c["situacao"] == "parado"),
            "horas_mes": sum(c["horas_mes"] for c in saida),
        }
        return jsonify({"status": "sucesso", "clientes": saida,
                        "resumo": resumo, "dias_parado": dias_parado}), 200
    except Exception as e:
        print("Erro em carteira_clientes:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar a carteira.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/clientes/<cliente_id>/conta', methods=['GET'])
def conta_cliente(cliente_id):
    """Detalhe de um cliente: projetos, horas por área e portal."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        hoje = datetime.now(timezone.utc).date().isoformat()
        mes = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()

        res = supabase.table("clientes").select("*").eq("id", cliente_id).limit(1).execute()
        if not res.data:
            return jsonify({"status": "erro", "mensagem": "Cliente não encontrado."}), 404
        cliente = res.data[0]

        todos = (supabase.table("projetos").select("*")
                 .eq("cliente_id", cliente_id).is_("excluido_em", "null").execute()).data or []
        projetos = filtrar_projetos_permitidos(todos)

        horas_proj, horas_mes_proj = {}, {}
        try:
            ids = [str(p["id"]) for p in projetos]
            if ids:
                passo, inicio = 1000, 0
                while True:
                    r = (supabase.table("time_logs")
                         .select("projeto_id, tempo_segundos, criado_em")
                         .in_("projeto_id", ids).range(inicio, inicio + passo - 1).execute())
                    if not r.data:
                        break
                    for l in r.data:
                        pid = str(l.get("projeto_id"))
                        seg = l.get("tempo_segundos") or 0
                        horas_proj[pid] = horas_proj.get(pid, 0) + seg
                        if str(l.get("criado_em") or '') >= mes:
                            horas_mes_proj[pid] = horas_mes_proj.get(pid, 0) + seg
                    if len(r.data) < passo:
                        break
                    inicio += passo
        except Exception as e:
            print("Aviso: time_logs indisponivel na conta:", e)

        ativos, concluidos, por_area = [], [], {}
        for p in projetos:
            pid = str(p["id"])
            h = round(horas_proj.get(pid, 0) / 3600.0)
            item = {
                "id": p["id"], "nome": p.get("nome_projeto"), "area": p.get("area"),
                "status": p.get("status"), "responsavel": p.get("responsavel"),
                "prazo": str(p.get("prazo_data") or '')[:10] or None, "horas": h,
            }
            if p.get("status") in STATUS_ENCERRADOS:
                concluidos.append(item)
            else:
                ativos.append(item)
            a = p.get("area") or "Sem área"
            por_area[a] = por_area.get(a, 0) + h

        ativos.sort(key=lambda x: (x["prazo"] or "9999", -x["horas"]))
        prazo_prox = next((p["prazo"] for p in ativos if p["prazo"]), None)

        pessoas = []
        try:
            ext = (supabase.table("usuarios")
                   .select("id, nome, cargo, email, ativo, ultimo_acesso")
                   .eq("tipo_usuario", "externo")
                   .eq("cliente_vinculado_id", cliente_id).execute()).data or []
            pessoas = [{"id": u["id"], "nome": u.get("nome"), "cargo": u.get("cargo"),
                        "email": u.get("email"), "ativo": u.get("ativo") is not False,
                        "ultimo_acesso": u.get("ultimo_acesso")} for u in ext]
        except Exception as e:
            print("Aviso: usuarios do portal indisponiveis:", e)

        origem = None
        if cliente.get("lead_id"):
            try:
                l = (supabase.table("leads").select("origem, responsavel, movido_em")
                     .eq("id", cliente["lead_id"]).limit(1).execute())
                if l.data:
                    origem = l.data[0]
            except Exception as e:
                print("Aviso: lead de origem indisponivel:", e)

        return jsonify({
            "status": "sucesso",
            "cliente": cliente,
            "ativos": ativos,
            "concluidos": concluidos[:10],
            "total_concluidos": len(concluidos),
            "horas_area": sorted(({"area": k, "horas": v} for k, v in por_area.items()
                                  if v > 0), key=lambda x: -x["horas"]),
            "horas_mes": round(sum(horas_mes_proj.values()) / 3600.0),
            "horas_total": round(sum(horas_proj.values()) / 3600.0),
            "prazo_proximo": prazo_prox,
            "atrasados": sum(1 for p in ativos if p["prazo"] and p["prazo"] < hoje),
            "pessoas": pessoas,
            "origem": origem,
        }), 200
    except Exception as e:
        print("Erro em conta_cliente:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar o cliente.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/clientes/<cliente_id>/mapa', methods=['GET'])
def mapa_cliente(cliente_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        # Dados do cliente
        res_cli = supabase.table("clientes").select("*").eq("id", cliente_id).execute()
        if not res_cli.data:
            return jsonify({"status": "erro", "mensagem": "Cliente não encontrado."}), 404
        cliente = res_cli.data[0]

        # Projetos do cliente (ignora os que estão na lixeira)
        res_proj = supabase.table("projetos").select("*").eq("cliente_id", cliente_id).execute()
        projetos = [p for p in res_proj.data if not p.get("excluido_em")]

        # Tempo dedicado por projeto (paginação para superar limite de 1000)
        ids_projetos = [str(p["id"]) for p in projetos]
        tempos = {}
        if ids_projetos:
            page_size = 1000
            offset = 0
            while True:
                res_t = supabase.table("time_logs").select("projeto_id, tempo_segundos").in_("projeto_id", ids_projetos).range(offset, offset + page_size - 1).execute()
                if not res_t.data:
                    break
                for log in res_t.data:
                    pid = str(log["projeto_id"])
                    tempos[pid] = tempos.get(pid, 0) + (log["tempo_segundos"] or 0)
                if len(res_t.data) < page_size:
                    break
                offset += page_size

        # Consolida
        tempo_total_cliente = 0
        for p in projetos:
            pid = str(p["id"])
            p["tempo_total_segundos"] = tempos.get(pid, 0)
            tempo_total_cliente += p["tempo_total_segundos"]

        # KPIs
        finalizados = [p for p in projetos if p.get("status") in ["Finalizado", "Cancelado"]]
        ativos = [p for p in projetos if p.get("status") not in ["Finalizado", "Cancelado"]]

        return jsonify({
            "status": "sucesso",
            "cliente": cliente,
            "projetos": projetos,
            "kpis": {
                "total_projetos": len(projetos),
                "ativos": len(ativos),
                "finalizados": len(finalizados),
                "tempo_total_segundos": tempo_total_cliente
            }
        }), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no mapa do cliente: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# --- DASHBOARD / BI (gestor + admin) ---

@app.route('/dashboard')
def dashboard_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    liberado = (session.get('nivel_acesso') in ['admin', 'gestor']
                or pode_acessar_modulo('dashboard'))
    if not liberado:
        return redirect(url_for('index'))
    return render_template('dashboard.html',
                           usuario_nome=session.get('usuario_nome'),
                           nivel_acesso=session.get('nivel_acesso'),
                           tipo_usuario=session.get('tipo_usuario', 'interno'),
                           papel_externo=session.get('papel_externo', ''),
                           perm_modulos=session.get('perm_modulos', []))

@app.route('/api/dashboard', methods=['GET'])
def dados_dashboard():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    liberado = (session.get('nivel_acesso') in ['admin', 'gestor']
                or pode_acessar_modulo('dashboard'))
    if not liberado:
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        # Filtros opcionais
        f_area = request.args.get('area')
        f_resp = request.args.get('responsavel')
        f_cliente = request.args.get('cliente_id')
        # Datas: cada uma com propósito claro
        f_horas_ini = request.args.get('horas_ini') or request.args.get('inicio')  # registro de time_logs
        f_horas_fim = request.args.get('horas_fim') or request.args.get('fim')
        f_abertura_ini = request.args.get('abertura_ini')   # data de abertura do projeto
        f_abertura_fim = request.args.get('abertura_fim')
        f_fech_ini = request.args.get('fechamento_ini')     # data de conclusão do projeto
        f_fech_fim = request.args.get('fechamento_fim')

        def _dia(v): return str(v)[:10] if v else None

        # Projetos (fora da lixeira)
        res_proj = supabase.table("projetos").select("*").execute()
        projetos = [p for p in res_proj.data if not p.get("excluido_em")]

        # Filtros categóricos
        if f_area: projetos = [p for p in projetos if p.get("area") == f_area]
        if f_resp: projetos = [p for p in projetos if p.get("responsavel") == f_resp]
        if f_cliente: projetos = [p for p in projetos if str(p.get("cliente_id")) == str(f_cliente)]

        # Filtro por data de ABERTURA (created_em/data_inicio) — afeta todo o conjunto de projetos
        if f_abertura_ini or f_abertura_fim:
            def _abriu_no_periodo(p):
                d = _dia(p.get("data_inicio") or p.get("criado_em"))
                if not d: return False
                if f_abertura_ini and d < f_abertura_ini: return False
                if f_abertura_fim and d > f_abertura_fim: return False
                return True
            projetos = [p for p in projetos if _abriu_no_periodo(p)]

        # Filtro por data de FECHAMENTO — restringe às contagens de finalizados;
        # para não zerar métricas de ativos, guardamos um conjunto separado.
        tem_filtro_fech = bool(f_fech_ini or f_fech_fim)
        def _fechou_no_periodo(p):
            # SOMENTE "Finalizado" conta como fechamento real (Cancelado não é entrega)
            if p.get("status") != "Finalizado": return False
            d = _dia(p.get("data_conclusao"))
            if not d: return False
            if f_fech_ini and d < f_fech_ini: return False
            if f_fech_fim and d > f_fech_fim: return False
            return True

        # Se há filtro de fechamento, o "universo" de finalizados é o que fechou no período.
        # Os demais painéis (status, área, ativos) passam a refletir só o recorte filtrado.
        if tem_filtro_fech:
            projetos = [p for p in projetos if _fechou_no_periodo(p)]

        ids_proj = set(str(p["id"]) for p in projetos)

        # Time logs (paginado)
        logs = []
        page_size = 1000
        offset = 0
        while True:
            res_t = supabase.table("time_logs").select("*").range(offset, offset + page_size - 1).execute()
            if not res_t.data: break
            logs.extend(res_t.data)
            if len(res_t.data) < page_size: break
            offset += page_size

        # Filtra logs pelos projetos visíveis e pelo período de REGISTRO DE HORAS
        def log_no_periodo(log):
            d = log.get("data_inicio_atividade") or log.get("criado_em")
            if not d: return True
            dia = str(d)[:10]
            if f_horas_ini and dia < f_horas_ini: return False
            if f_horas_fim and dia > f_horas_fim: return False
            return True

        # Se filtro de horas está ativo, restringe logs aos projetos visíveis? 
        # Não: horas registradas devem refletir o período independente do recorte de projeto,
        # exceto pelos filtros categóricos (área/resp/cliente) que restringem via ids_proj.
        logs = [l for l in logs if str(l.get("projeto_id")) in ids_proj and log_no_periodo(l)]
        # variáveis legadas usadas mais abaixo
        f_inicio = f_horas_ini
        f_fim = f_horas_fim

        # ===== KPIs GERAIS =====
        total_projetos = len(projetos)
        ativos = [p for p in projetos if p.get("status") not in ["Finalizado", "Cancelado"]]
        # "Finalizados" conta SOMENTE status "Finalizado" (entrega real p/ comissionamento).
        finalizados = [p for p in projetos if p.get("status") == "Finalizado"]
        cancelados = [p for p in projetos if p.get("status") == "Cancelado"]
        tempo_total = sum((l.get("tempo_segundos") or 0) for l in logs)

        # Projetos atrasados
        hoje = hoje_br().isoformat()
        atrasados = 0
        for p in ativos:
            prazo = p.get("prazo_data")
            if prazo and str(prazo)[:10] < hoje:
                atrasados += 1

        # ===== DISTRIBUIÇÃO POR STATUS =====
        por_status = {}
        for p in projetos:
            s = p.get("status") or "Sem status"
            por_status[s] = por_status.get(s, 0) + 1

        # ===== DISTRIBUIÇÃO POR ÁREA =====
        por_area = {}
        for p in projetos:
            a = p.get("area") or "Sem área"
            por_area[a] = por_area.get(a, 0) + 1

        # ===== TEMPO POR COLABORADOR =====
        tempo_colab = {}
        for l in logs:
            c = l.get("colaborador") or "Não identificado"
            tempo_colab[c] = tempo_colab.get(c, 0) + (l.get("tempo_segundos") or 0)
        ranking_colab = sorted([{"nome": k, "segundos": v} for k, v in tempo_colab.items()], key=lambda x: x["segundos"], reverse=True)

        # ===== PRINCIPAIS ATIVIDADES =====
        atividades = {}
        for l in logs:
            t = (l.get("descricao_tarefa") or "Sem descrição").strip()
            if t not in atividades:
                atividades[t] = {"qtd": 0, "segundos": 0}
            atividades[t]["qtd"] += 1
            atividades[t]["segundos"] += (l.get("tempo_segundos") or 0)
        top_atividades = sorted([{"atividade": k, **v} for k, v in atividades.items()], key=lambda x: x["segundos"], reverse=True)[:10]

        # ===== TEMPO POR CLIENTE (top) =====
        cliente_nomes = {}
        res_cli = supabase.table("clientes").select("id, nome_empresa").execute()
        for c in res_cli.data:
            cliente_nomes[str(c["id"])] = c["nome_empresa"]
        proj_para_cliente = {str(p["id"]): str(p.get("cliente_id")) for p in projetos}
        tempo_cliente = {}
        for l in logs:
            cid = proj_para_cliente.get(str(l.get("projeto_id")))
            if not cid or cid == "None": continue
            nome = cliente_nomes.get(cid, "Desconhecido")
            tempo_cliente[nome] = tempo_cliente.get(nome, 0) + (l.get("tempo_segundos") or 0)
        top_clientes = sorted([{"cliente": k, "segundos": v} for k, v in tempo_cliente.items()], key=lambda x: x["segundos"], reverse=True)[:8]

        # ===== EVOLUÇÃO TEMPORAL (tempo por dia, últimos registros) =====
        tempo_por_dia = {}
        for l in logs:
            d = l.get("data_inicio_atividade") or l.get("criado_em")
            if not d: continue
            dia = str(d)[:10]
            tempo_por_dia[dia] = tempo_por_dia.get(dia, 0) + (l.get("tempo_segundos") or 0)
        evolucao = sorted([{"dia": k, "segundos": v} for k, v in tempo_por_dia.items()], key=lambda x: x["dia"])[-30:]

        # ===== OPÇÕES PARA FILTROS =====
        todas_areas = sorted(list(set(p.get("area") for p in res_proj.data if p.get("area") and not p.get("excluido_em"))))
        todos_resp = sorted(list(set(p.get("responsavel") for p in res_proj.data if p.get("responsavel") and not p.get("excluido_em"))))
        todos_clientes = sorted([{"id": str(c["id"]), "nome": c["nome_empresa"]} for c in res_cli.data], key=lambda x: x["nome"])

        # ===== 1. PROJETOS ATRASADOS (lista detalhada) =====
        lista_atrasados = []
        for p in ativos:
            prazo = p.get("prazo_data")
            if prazo and str(prazo)[:10] < hoje:
                dias_atraso = (hoje_br() - datetime.strptime(str(prazo)[:10], "%Y-%m-%d").date()).days
                lista_atrasados.append({
                    "nome": p.get("nome_projeto"),
                    "responsavel": p.get("responsavel") or "—",
                    "area": p.get("area") or "—",
                    "prazo": str(prazo)[:10],
                    "dias_atraso": dias_atraso,
                    "status": p.get("status")
                })
        lista_atrasados = sorted(lista_atrasados, key=lambda x: x["dias_atraso"], reverse=True)

        # ===== 2. FLUXO DE NOVOS PROJETOS (por mês e por dia) =====
        novos_por_mes = {}
        novos_por_dia = {}
        for p in projetos:
            d = p.get("data_inicio") or p.get("criado_em")
            if not d: continue
            dia = str(d)[:10]
            mes = str(d)[:7]  # YYYY-MM
            novos_por_mes[mes] = novos_por_mes.get(mes, 0) + 1
            novos_por_dia[dia] = novos_por_dia.get(dia, 0) + 1
        fluxo_mensal = sorted([{"periodo": k, "qtd": v} for k, v in novos_por_mes.items()], key=lambda x: x["periodo"])
        fluxo_diario = sorted([{"periodo": k, "qtd": v} for k, v in novos_por_dia.items()], key=lambda x: x["periodo"])[-31:]

        # ===== 3. % DE OCUPAÇÃO POR COLABORADOR (base: dias úteis × 8h) =====
        # Determina o período de análise
        dias_com_log = [str(l.get("data_inicio_atividade") or l.get("criado_em"))[:10] for l in logs if (l.get("data_inicio_atividade") or l.get("criado_em"))]
        if f_inicio and f_fim:
            dt_ini = datetime.strptime(f_inicio, "%Y-%m-%d").date()
            dt_fim = datetime.strptime(f_fim, "%Y-%m-%d").date()
        elif dias_com_log:
            dt_ini = datetime.strptime(min(dias_com_log), "%Y-%m-%d").date()
            dt_fim = datetime.strptime(max(dias_com_log), "%Y-%m-%d").date()
        else:
            dt_ini = dt_fim = hoje_br()

        # Conta dias úteis (seg-sex) no período
        dias_uteis = 0
        d_cursor = dt_ini
        from datetime import timedelta
        while d_cursor <= dt_fim:
            if d_cursor.weekday() < 5:  # 0-4 = seg-sex
                dias_uteis += 1
            d_cursor += timedelta(days=1)
        if dias_uteis == 0: dias_uteis = 1

        segundos_esperados = dias_uteis * 8 * 3600  # 8h por dia útil
        ocupacao = []
        for nome, seg in tempo_colab.items():
            pct = round((seg / segundos_esperados) * 100, 1)
            ocupacao.append({"nome": nome, "segundos": seg, "percentual": pct, "esperado_segundos": segundos_esperados})
        ocupacao = sorted(ocupacao, key=lambda x: x["percentual"], reverse=True)

        # ===== 4. PROJETOS EM ANDAMENTO POR COLABORADOR =====
        andamento_colab = {}
        for p in ativos:
            r = p.get("responsavel") or "Não atribuído"
            andamento_colab[r] = andamento_colab.get(r, 0) + 1
        proj_por_colab = sorted([{"nome": k, "qtd": v} for k, v in andamento_colab.items()], key=lambda x: x["qtd"], reverse=True)

        # ============================================================
        # ===== NOVAS MÉTRICAS DE FLUXO (lead time, cycle time, etc) =====
        # ============================================================
        from datetime import timedelta as _td

        def _parse(v):
            try: return datetime.strptime(str(v)[:10], "%Y-%m-%d").date()
            except: return None

        # Carrega histórico de colunas (para cycle time do R&S e etapas)
        historico = []
        try:
            off = 0
            while True:
                rh = supabase.table("historico_colunas").select("*").range(off, off + 999).execute()
                if not rh.data: break
                historico.extend(rh.data)
                if len(rh.data) < 1000: break
                off += 1000
        except Exception as e:
            print(f"[BI] historico_colunas indisponivel: {str(e)}")

        # Indexa histórico por projeto (ordenado por data)
        hist_por_proj = {}
        for h in historico:
            pid = str(h.get("projeto_id"))
            hist_por_proj.setdefault(pid, []).append(h)
        for pid in hist_por_proj:
            hist_por_proj[pid].sort(key=lambda x: str(x.get("criado_em") or ""))

        # Etapa de corte do cycle time interno no R&S: quando ENTRA em "Entrevista com Cliente",
        # o trabalho interno terminou (a última etapa interna é "Produção de Relatório").
        RS_CORTE = "Entrevista com Cliente"
        RS_AREAS = {"recrutamento", "r&s", "recrutamento e seleção", "recrutamento e seleÇÃo"}

        def eh_rs(proj):
            a = (proj.get("area") or "").strip().lower()
            return "recrut" in a or a == "r&s"

        def momento_corte_rs(pid):
            """Retorna o datetime em que o projeto entrou em 'Entrevista com Cliente'."""
            for h in hist_por_proj.get(str(pid), []):
                if (h.get("status_novo") or "") == RS_CORTE:
                    return _parse(h.get("criado_em"))
            return None

        # Calcula lead time e cycle time por projeto finalizado
        lead_times = []       # dias: abertura -> conclusão
        cycle_times = []      # dias: início -> conclusão (ou corte no R&S)
        detalhe_tempos = []
        for p in projetos:
            if p.get("status") != "Finalizado":
                continue
            abertura = _parse(p.get("criado_em"))
            inicio = _parse(p.get("data_inicio")) or abertura
            conclusao = _parse(p.get("data_conclusao"))
            if not conclusao:
                continue
            # aplica filtro de data de fechamento
            cdia = _dia(p.get("data_conclusao"))
            if f_fech_ini and cdia and cdia < f_fech_ini: continue
            if f_fech_fim and cdia and cdia > f_fech_fim: continue

            lead = (conclusao - abertura).days if abertura else None
            # cycle time: R&S usa corte na entrada de "Entrevista com Cliente"
            fim_cycle = conclusao
            if eh_rs(p):
                corte = momento_corte_rs(p["id"])
                if corte: fim_cycle = corte
            cycle = (fim_cycle - inicio).days if inicio else None

            if lead is not None and lead >= 0: lead_times.append(lead)
            if cycle is not None and cycle >= 0: cycle_times.append(cycle)
            detalhe_tempos.append({
                "nome": p.get("nome_projeto"),
                "area": p.get("area") or "—",
                "abertura": _dia(p.get("criado_em")),
                "conclusao": cdia,
                "lead": lead if (lead is not None and lead >= 0) else None,
                "cycle": cycle if (cycle is not None and cycle >= 0) else None,
                "eh_rs": eh_rs(p)
            })

        def _media(lst): return round(sum(lst)/len(lst), 1) if lst else None
        lead_medio = _media(lead_times)
        cycle_medio = _media(cycle_times)

        # Tempo médio de tarefa (time_logs) — em segundos e formatado
        tarefas_validas = [l.get("tempo_segundos") or 0 for l in logs if (l.get("tempo_segundos") or 0) > 0]
        tempo_medio_tarefa = round(sum(tarefas_validas)/len(tarefas_validas)) if tarefas_validas else 0

        # ===== INICIADOS x FINALIZADOS (por mês) =====
        # Iniciados: por data_inicio (ou criado_em). Finalizados: por data_conclusao.
        iniciados_mes = {}
        finalizados_mes = {}
        lista_iniciados = []
        lista_finalizados = []
        for p in projetos:
            # abertura/início
            di = p.get("data_inicio") or p.get("criado_em")
            if di:
                mes = str(di)[:7]
                dia = str(di)[:10]
                # filtro de abertura
                ok_ab = True
                if f_abertura_ini and dia < f_abertura_ini: ok_ab = False
                if f_abertura_fim and dia > f_abertura_fim: ok_ab = False
                if ok_ab:
                    iniciados_mes[mes] = iniciados_mes.get(mes, 0) + 1
                    lista_iniciados.append({
                        "nome": p.get("nome_projeto"),
                        "area": p.get("area") or "—",
                        "data": dia,
                        "responsavel": p.get("responsavel") or "—",
                        "cliente": cliente_nomes.get(str(p.get("cliente_id")), "—"),
                        "status": p.get("status")
                    })
            # conclusão — SOMENTE status "Finalizado" conta (Cancelado NÃO é entrega)
            dc = p.get("data_conclusao")
            if dc and p.get("status") == "Finalizado":
                mes = str(dc)[:7]
                dia = str(dc)[:10]
                ok_fe = True
                if f_fech_ini and dia < f_fech_ini: ok_fe = False
                if f_fech_fim and dia > f_fech_fim: ok_fe = False
                if ok_fe:
                    finalizados_mes[mes] = finalizados_mes.get(mes, 0) + 1
                    lista_finalizados.append({
                        "nome": p.get("nome_projeto"),
                        "area": p.get("area") or "—",
                        "data": dia,
                        "responsavel": p.get("responsavel") or "—",
                        "cliente": cliente_nomes.get(str(p.get("cliente_id")), "—"),
                        "status": p.get("status")
                    })

        # Une os meses das duas séries
        todos_meses = sorted(set(list(iniciados_mes.keys()) + list(finalizados_mes.keys())))
        serie_inic_fin = [{"periodo": m, "iniciados": iniciados_mes.get(m, 0), "finalizados": finalizados_mes.get(m, 0)} for m in todos_meses]
        lista_iniciados = sorted(lista_iniciados, key=lambda x: x["data"], reverse=True)
        lista_finalizados = sorted(lista_finalizados, key=lambda x: x["data"], reverse=True)

        # Distribuição de lead/cycle em faixas (para histograma)
        def faixas(lst):
            fx = {"0-3d": 0, "4-7d": 0, "8-15d": 0, "16-30d": 0, "30d+": 0}
            for v in lst:
                if v <= 3: fx["0-3d"] += 1
                elif v <= 7: fx["4-7d"] += 1
                elif v <= 15: fx["8-15d"] += 1
                elif v <= 30: fx["16-30d"] += 1
                else: fx["30d+"] += 1
            return fx

        # ============================================================
        # ===== SAÚDE DOS DADOS — auditoria de integridade =====
        # Verifica registros que comprometem as métricas, para que o
        # usuário confie (ou não) nos números direto pelo dashboard.
        # Usa TODOS os projetos permitidos, sem os filtros de recorte.
        # ============================================================
        try:
            _res_all = supabase.table("projetos").select("*").execute()
            _proj_all = [p for p in _res_all.data if not p.get("excluido_em")]
            _proj_all = filtrar_projetos_permitidos(_proj_all)
            # aplica só filtros categóricos (não os de data), para auditar o universo relevante
            if f_area: _proj_all = [p for p in _proj_all if p.get("area") == f_area]
            if f_resp: _proj_all = [p for p in _proj_all if p.get("responsavel") == f_resp]
            if f_cliente: _proj_all = [p for p in _proj_all if str(p.get("cliente_id")) == str(f_cliente)]
        except Exception:
            _proj_all = projetos

        _finalizados_all = [p for p in _proj_all if p.get("status") in ["Finalizado", "Cancelado"]]
        _ativos_all = [p for p in _proj_all if p.get("status") not in ["Finalizado", "Cancelado"]]

        # Projetos que TÊM registro de timer (ao menos 1 log)
        _proj_com_log = set(str(l.get("projeto_id")) for l in logs if (l.get("tempo_segundos") or 0) > 0)

        # Problemas de integridade (cada um é uma lista de projetos afetados)
        prob_sem_conclusao = []   # finalizado sem data_conclusao -> some do filtro de fechamento
        prob_sem_inicio = []      # sem data_inicio -> cycle time impreciso
        prob_rs_sem_etapa = []    # R&S finalizado sem passar por "Entrevista com Cliente" no histórico
        prob_sem_timer = []       # projeto (ativo ou finalizado) sem nenhum registro de timer
        prob_sem_responsavel = [] # sem responsável definido

        for p in _proj_all:
            pid = str(p["id"])
            nome = p.get("nome_projeto") or "—"
            area = p.get("area") or "—"
            item = {"nome": nome, "area": area, "status": p.get("status") or "—", "responsavel": p.get("responsavel") or "—"}
            eh_final = p.get("status") in ["Finalizado", "Cancelado"]
            if eh_final and not p.get("data_conclusao"):
                prob_sem_conclusao.append(item)
            if not p.get("data_inicio"):
                prob_sem_inicio.append(item)
            # R&S finalizado sem a etapa de corte registrada no histórico
            _a = (p.get("area") or "").strip().lower()
            _eh_rs = ("recrut" in _a or _a == "r&s")
            if _eh_rs and eh_final:
                _tem_corte = any((h.get("status_novo") or "") == RS_CORTE for h in hist_por_proj.get(pid, []))
                if not _tem_corte:
                    prob_rs_sem_etapa.append(item)
            if pid not in _proj_com_log:
                prob_sem_timer.append(item)
            if not p.get("responsavel"):
                prob_sem_responsavel.append(item)

        _tot = len(_proj_all) or 1
        def _pct_ok(n_problemas):
            return round((_tot - n_problemas) / _tot * 100)

        # Score geral de confiabilidade (média ponderada dos indicadores mais críticos)
        _peso_score = [
            (_pct_ok(len(prob_sem_conclusao)), 3),   # crítico p/ fechamento/comissionamento
            (_pct_ok(len(prob_sem_inicio)), 2),       # cycle time
            (_pct_ok(len(prob_sem_timer)), 2),        # horas
            (_pct_ok(len(prob_sem_responsavel)), 1),
        ]
        _score = round(sum(v*w for v, w in _peso_score) / sum(w for _, w in _peso_score))

        saude_dados = {
            "score": _score,
            "total_projetos": len(_proj_all),
            "total_finalizados": len(_finalizados_all),
            "com_timer": len(_proj_com_log),
            "indicadores": [
                {
                    "chave": "sem_conclusao",
                    "titulo": "Finalizados sem data de conclusão",
                    "descricao": "Não aparecem no filtro de fechamento (afeta comissionamento).",
                    "severidade": "alta",
                    "qtd": len(prob_sem_conclusao),
                    "base": len(_finalizados_all),
                    "projetos": prob_sem_conclusao[:30]
                },
                {
                    "chave": "sem_inicio",
                    "titulo": "Projetos sem data de início",
                    "descricao": "O cycle time usa a abertura como aproximação.",
                    "severidade": "media",
                    "qtd": len(prob_sem_inicio),
                    "base": len(_proj_all),
                    "projetos": prob_sem_inicio[:30]
                },
                {
                    "chave": "rs_sem_etapa",
                    "titulo": "R&S sem passagem por 'Entrevista com Cliente'",
                    "descricao": "O cycle time interno do R&S não é recortado corretamente.",
                    "severidade": "media",
                    "qtd": len(prob_rs_sem_etapa),
                    "base": len([p for p in _finalizados_all if ('recrut' in (p.get('area') or '').lower())]),
                    "projetos": prob_rs_sem_etapa[:30]
                },
                {
                    "chave": "sem_timer",
                    "titulo": "Projetos sem registro de timer",
                    "descricao": "Não entram nas métricas de horas e ocupação.",
                    "severidade": "baixa",
                    "qtd": len(prob_sem_timer),
                    "base": len(_proj_all),
                    "projetos": prob_sem_timer[:30]
                },
                {
                    "chave": "sem_responsavel",
                    "titulo": "Projetos sem responsável",
                    "descricao": "Não aparecem no ranking por responsável.",
                    "severidade": "baixa",
                    "qtd": len(prob_sem_responsavel),
                    "base": len(_proj_all),
                    "projetos": prob_sem_responsavel[:30]
                }
            ]
        }


        metricas_fluxo = {
            "lead_medio": lead_medio,
            "cycle_medio": cycle_medio,
            "tempo_medio_tarefa_seg": tempo_medio_tarefa,
            "total_finalizados_periodo": len(lead_times),
            "lead_faixas": faixas(lead_times),
            "cycle_faixas": faixas(cycle_times),
            "serie_iniciados_finalizados": serie_inic_fin,
            "lista_iniciados": lista_iniciados[:50],
            "lista_finalizados": lista_finalizados[:50],
            "detalhe_tempos": sorted([d for d in detalhe_tempos if d["lead"] is not None], key=lambda x: x["lead"], reverse=True)[:50],
            "qtd_iniciados": len(lista_iniciados),
            "qtd_finalizados": len(lista_finalizados)
        }


        return jsonify({
            "status": "sucesso",
            "metricas_fluxo": metricas_fluxo,
            "saude_dados": saude_dados,
            "kpis": {
                "total_projetos": total_projetos,
                "ativos": len(ativos),
                "finalizados": len(finalizados),
                "atrasados": atrasados,
                "tempo_total_segundos": tempo_total,
                "total_sessoes": len(logs)
            },
            "por_status": por_status,
            "por_area": por_area,
            "ranking_colaboradores": ranking_colab,
            "top_atividades": top_atividades,
            "top_clientes": top_clientes,
            "evolucao": evolucao,
            "lista_atrasados": lista_atrasados,
            "fluxo_mensal": fluxo_mensal,
            "fluxo_diario": fluxo_diario,
            "ocupacao": ocupacao,
            "dias_uteis": dias_uteis,
            "proj_por_colab": proj_por_colab,
            "filtros": {
                "areas": todas_areas,
                "responsaveis": todos_resp,
                "clientes": todos_clientes
            }
        }), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no Dashboard: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# --- PLANEJAMENTO DIÁRIO ---

@app.route('/planejamento')
@app.route('/agenda')
def planejamento():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    return render_template('planejamento.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

@app.route('/crm')
def pagina_crm():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    return render_template('crm.html',
                           usuario_nome=session.get('usuario_nome', ''),
                           nivel_acesso=session.get('nivel_acesso', ''),
                           tipo_usuario=session.get('tipo_usuario', 'interno'),
                           papel_externo=session.get('papel_externo', ''),
                           perm_modulos=session.get('perm_modulos', []))


# Para onde o lead cai ao trocar de funil. Espelha ENTRADA no crm.html;
# a validação fica aqui porque o cliente não pode ser a fonte da verdade.
ENTRADA_FUNIL = {"qualificacao": "Prospecção", "fechamento": "Agendamento",
                 "relacionamento": "Backlog", "nutricao": "Backlog"}
FUNIS_VALIDOS = set(ENTRADA_FUNIL.keys())

# Colunas de cada funil. O cliente não pode ser a fonte da verdade sobre
# para onde um lead pode ir, então a lista vive aqui também.
COLUNAS_FUNIL = {
    "qualificacao": ["Prospecção", "Contato", "Follow up 1", "Follow up 2",
                     "Follow up 3", "Follow up 4", "Ganho", "Nutrição", "Perdido"],
    "fechamento":   ["Agendamento", "Proposta", "Negociação", "Ganho", "Nutrição"],
    "relacionamento": ["Backlog", "Pesquisa de satisfação", "Follow up 1", "Follow up 2",
                       "Follow up 3", "Follow up 4", "Ganho", "Nutrição"],
    "nutricao":     ["Backlog"] + [f"Contato {i}" for i in range(1, 11)]
                    + ["Ganho", "Encerrado"],
}

# Última tentativa de cada funil. Chegar nela sem avançar é o sinal de
# que o lead esgotou o ciclo — a tela sugere a saída, sem mover sozinha.
ULTIMO_FUP = {"qualificacao": "Follow up 4", "relacionamento": "Follow up 4",
              "nutricao": "Contato 10"}


@app.route('/api/leads', methods=['GET'])
def listar_leads():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        res = (supabase.table("leads").select("*")
               .is_("excluido_em", "null")
               .order("movido_em", desc=True).execute())
        return jsonify({"status": "sucesso", "leads": res.data or []}), 200
    except Exception as e:
        print("Erro em listar_leads:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar leads.", "detalhe": str(e)[:300]}), 500


@app.route('/api/leads', methods=['POST'])
def criar_lead():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.get_json() or {}
        if not (d.get("empresa") or d.get("contato")):
            return jsonify({"status": "erro", "mensagem": "Informe a empresa ou o contato."}), 400
        funil = d.get("funil", "qualificacao")
        if funil not in FUNIS_VALIDOS:
            return jsonify({"status": "erro", "mensagem": "Funil inválido."}), 400

        agora = datetime.now(timezone.utc).isoformat()
        novo = {
            "empresa": (d.get("empresa") or "").strip(),
            "contato": (d.get("contato") or "").strip(),
            "telefone": (d.get("telefone") or "").strip(),
            "email": (d.get("email") or "").strip(),
            "produto": d.get("produto") or None,
            "responsavel": d.get("responsavel") or session.get('usuario_nome', ''),
            "origem": d.get("origem") or None,
            # Segmento e localização: o closer precisa dos dois para
            # preparar a reunião. São exigidos no portão de Ganho.
            "segmento": d.get("segmento") or None,
            "cidade": (d.get("cidade") or "").strip() or None,
            "estado": (d.get("estado") or "").strip().upper()[:2] or None,
            "anotacoes": (d.get("anotacoes") or "").strip(),
            "proximo_contato": d.get("proximo_contato") or None,
            "valor_estimado": d.get("valor_estimado") or None,
            "funil": funil,
            "coluna": d.get("coluna") or ENTRADA_FUNIL[funil],
            "movido_em": agora,
        }
        res = supabase.table("leads").insert(novo).execute()
        return jsonify({"status": "sucesso", "lead": (res.data or [None])[0]}), 201
    except Exception as e:
        print("Erro em criar_lead:", e)
        # Ferramenta interna e autenticada: devolver o motivo economiza
        # uma ida ao log do servidor a cada erro.
        return jsonify({"status": "erro", "mensagem": "Erro ao criar lead.", "detalhe": str(e)[:300]}), 500


@app.route('/api/leads/<lead_id>', methods=['PUT'])
def atualizar_lead(lead_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.get_json() or {}
        # Lista fechada: funil e coluna só mudam pela rota de mover,
        # que registra a trilha e aplica as passagens.
        campos = ["empresa", "contato", "telefone", "email", "produto", "responsavel",
                  "origem", "segmento", "cidade", "estado", "anotacoes",
                  "proximo_contato", "valor_estimado", "cnpj", "canal_proposta"]
        upd = {k: d[k] for k in campos if k in d}
        if not upd:
            return jsonify({"status": "erro", "mensagem": "Nada a atualizar."}), 400
        supabase.table("leads").update(upd).eq("id", lead_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em atualizar_lead:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao atualizar lead.", "detalhe": str(e)[:300]}), 500


@app.route('/api/leads/<lead_id>', methods=['DELETE'])
def excluir_lead(lead_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('nivel_acesso') not in ('admin', 'gestor'):
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        # Exclusão lógica: o histórico de movimentos continua fazendo sentido.
        supabase.table("leads").update(
            {"excluido_em": datetime.now(timezone.utc).isoformat(),
             "excluido_por": session.get('usuario_nome')}
        ).eq("id", lead_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em excluir_lead:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir lead."}), 500


@app.route('/api/leads/<lead_id>/movimentos', methods=['GET'])
def movimentos_lead(lead_id):
    """Trilha do lead entre funis e colunas, do mais recente ao mais antigo.
    A duração de cada etapa é calculada no cliente, pela diferença entre
    movimentos consecutivos — não precisa de coluna nova."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        res = (supabase.table("lead_movimentos").select("*")
               .eq("lead_id", lead_id)
               .order("criado_em", desc=True).execute())
        return jsonify({"status": "sucesso", "movimentos": res.data or []}), 200
    except Exception as e:
        print("Erro em movimentos_lead:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar histórico.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/leads/<lead_id>/mover', methods=['POST'])
def mover_lead(lead_id):
    """Move o lead de coluna e, quando a coluna é de saída, troca de funil.
    Registra a trilha em lead_movimentos — é dela que sai o tempo por etapa
    e o relatório de objeções."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.get_json() or {}
        coluna = d.get("coluna")
        if not coluna:
            return jsonify({"status": "erro", "mensagem": "Informe a coluna."}), 400

        atual = supabase.table("leads").select("*").eq("id", lead_id).limit(1).execute()
        if not atual.data:
            return jsonify({"status": "erro", "mensagem": "Lead não encontrado."}), 404
        lead = atual.data[0]

        destino = d.get("destino_funil")
        if destino and destino not in FUNIS_VALIDOS:
            return jsonify({"status": "erro", "mensagem": "Funil de destino inválido."}), 400

        agora = datetime.now(timezone.utc).isoformat()
        upd = {"movido_em": agora}
        if destino:
            upd["funil"] = destino
            upd["coluna"] = ENTRADA_FUNIL[destino]
        else:
            upd["coluna"] = coluna
        if d.get("proximo_contato"):
            upd["proximo_contato"] = d["proximo_contato"]

        supabase.table("leads").update(upd).eq("id", lead_id).execute()

        # Trilha. Falhar aqui não desfaz o movimento: o lead já andou.
        try:
            supabase.table("lead_movimentos").insert({
                "lead_id": lead_id,
                "de_funil": lead.get("funil"),
                "de_coluna": lead.get("coluna"),
                "para_funil": upd.get("funil", lead.get("funil")),
                "para_coluna": upd["coluna"],
                "objecao": d.get("objecao"),
                "objecao_detalhe": (d.get("objecao_detalhe") or "").strip() or None,
                "autor": session.get('usuario_nome', ''),
            }).execute()
        except Exception as e:
            print("Aviso: movimento nao registrado em lead_movimentos:", e)

        lead.update(upd)
        return jsonify({"status": "sucesso", "lead": lead}), 200
    except Exception as e:
        print("Erro em mover_lead:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao mover lead.", "detalhe": str(e)[:300]}), 500


@app.route('/feed')
def pagina_feed():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    return render_template('feed.html',
                           usuario_nome=session.get('usuario_nome', ''),
                           nivel_acesso=session.get('nivel_acesso', ''),
                           tipo_usuario=session.get('tipo_usuario', 'interno'),
                           papel_externo=session.get('papel_externo', ''),
                           perm_modulos=session.get('perm_modulos', []))


# Comunicado é voz institucional: só admin e gestor publicam.
# Os demais tipos ficam abertos ao time.
TIPOS_POST = ('comunicado', 'evento', 'celebracao', 'post')
BUCKET_FEED = 'feed'


def _pode_publicar(tipo):
    if session.get('tipo_usuario') == 'externo':
        return False
    if tipo == 'comunicado':
        return session.get('nivel_acesso') in ('admin', 'gestor')
    return True


def _pode_mexer_no_post(post):
    """Autor mexe no que é seu; admin e gestor mexem em tudo."""
    if session.get('nivel_acesso') in ('admin', 'gestor'):
        return True
    return (post.get('autor') or '') == session.get('usuario_nome', '')


@app.route('/api/permissoes/divergencias', methods=['GET'])
def listar_divergencias():
    """Divergências entre o modelo antigo e o novo, durante a migração.

    Enquanto esta lista estiver vazia por alguns dias de uso real,
    o modelo novo pode assumir com segurança.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('nivel_acesso') != 'admin':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        res = (supabase.table("auditoria").select("*")
               .eq("acao", "divergencia_permissao")
               .order("criado_em", desc=True).limit(300).execute())
        linhas = res.data or []

        # Agrupa por recurso + par de respostas: 200 divergências iguais
        # são um problema só, e é assim que precisa aparecer.
        resumo = {}
        for l in linhas:
            det = l.get("detalhe") or {}
            chave = (l.get("recurso"), det.get("antigo"), det.get("novo"), det.get("nivel"))
            if chave not in resumo:
                resumo[chave] = {
                    "recurso": l.get("recurso"),
                    "antigo": det.get("antigo"),
                    "novo": det.get("novo"),
                    "nivel": det.get("nivel"),
                    "papel": det.get("papel"),
                    "ocorrencias": 0,
                    "ultima": l.get("criado_em"),
                    "usuarios": set(),
                }
            resumo[chave]["ocorrencias"] += 1
            if l.get("usuario"):
                resumo[chave]["usuarios"].add(l["usuario"])

        saida = []
        for v in resumo.values():
            v["usuarios"] = sorted(v["usuarios"])
            saida.append(v)
        saida.sort(key=lambda x: -x["ocorrencias"])

        return jsonify({
            "status": "sucesso",
            "total": len(linhas),
            "distintas": len(saida),
            "divergencias": saida,
            "modo_paralelo": MODO_PARALELO,
        }), 200
    except Exception as e:
        print("Erro em listar_divergencias:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar.",
                        "detalhe": str(e)[:300]}), 500


# ============================================================
# ACESSOS — papéis, pessoas e auditoria
# ============================================================

def registrar_auditoria(acao, recurso, alvo_id, detalhe=None):
    """Grava uma ação no registro de acessos.

    Falha aqui nunca derruba a operação: perder um registro de
    auditoria é ruim, mas impedir o cadastro de alguém é pior.
    """
    try:
        supabase.table("auditoria").insert({
            "usuario": session.get('usuario_nome'),
            "usuario_id": str(session.get('usuario_id', '')),
            "acao": acao,
            "recurso": recurso,
            "alvo_id": str(alvo_id) if alvo_id else None,
            "detalhe": detalhe or {},
        }).execute()
    except Exception as e:
        print("Aviso: auditoria nao registrada:", e)


def pode_ver_lixeira():
    """Ver e restaurar. Apagar em definitivo exige lixeira.purgar."""
    return pode('lixeira.ver') or is_admin()


# Capacidades que só o nível Administrador concede. Permitir que
# virassem exceção individual esvaziaria o sentido dos níveis: qualquer
# pessoa poderia acabar com poder de administrar sem que o nível dela
# dissesse isso.
CAPS_SO_ADMIN = ('usuario.gerir', 'papel.gerir', 'auditoria.ver', 'lixeira.purgar')

# ============================================================
# O QUE É BASE E O QUE É DECISÃO
#
# Oferecer as 28 capacidades como exceção transformava a tela numa
# lista onde tudo parecia negociável, inclusive registrar tempo, que
# é a razão de a plataforma existir.
#
# BASE: todo interno tem, sempre. Não aparece como exceção porque
# não há decisão a tomar.
#
# OPCIONAIS: mudam de pessoa para pessoa e valem a pergunta.
# ============================================================
CAPS_BASE = (
    'projeto.ver',        # ver o quadro em que atua
    'projeto.solicitar',  # pedir card em outro quadro
    'tempo.registrar',    # lançar o próprio tempo
    'okr.ver',            # acompanhar os OKRs
    'feed.publicar',      # postar no mural
)

# Estas não são "tem ou não tem": são "vê só o seu ou vê o do quadro
# todo". O alcance é um seletor único que move todas de uma vez, em vez
# de dez decisões independentes que ninguém quer tomar.
CAPS_ALCANCE = (
    'projeto.editar',
    'tempo.ver',
    'crm.lead.ver',
    'crm.painel.ver',
    'cliente.ver',
)

CAPS_OPCIONAIS = (
    'crm.valor.ver',      # ver valor de contrato
    'dashboard.ver',      # abrir o painel
    'dados.exportar',     # exportar planilha
    'projeto.atribuir',   # direcionar card para alguém
    'projeto.excluir',    # mandar projeto para a lixeira
    'cliente.gerir',      # cadastrar e editar cliente
    'crm.lead.editar',    # trabalhar os funis
    'okr.gerir',          # criar e editar OKR
    'feed.comunicado',    # publicar comunicado geral
    'feed.moderar',       # moderar o mural
    'comentario.excluir', # apagar comentário de outro
    'crm.lead.excluir',   # excluir lead
    'cliente.portal.gerir', # liberar acesso do cliente ao portal
    'lixeira.ver',        # ver a lixeira
)


def pode_gerir_acessos():
    """So administrador configura acessos.

    Delegado ao modulo para existir uma definicao so de "e admin" --
    duas definicoes divergem no primeiro caso de borda.
    """
    return acessos_v2.sou_admin()


# ============================================================
# PAINEL — operação e comercial
#
# Todo cálculo acontece aqui, no servidor: a tela recebe números
# prontos. Assim a mesma conta não é reescrita no JavaScript, e o
# escopo de permissão é aplicado antes de qualquer dado sair.
# ============================================================

STATUS_ENCERRADOS = ('Finalizado', 'Cancelado')
STATUS_PARADOS = ('Backlog', 'Não Iniciado', 'Pausado')


def _dias_desde(valor):
    """Dias entre a data informada e agora. None vira 0."""
    if not valor:
        return 0
    try:
        dt = datetime.fromisoformat(str(valor).replace('Z', '+00:00'))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt).days)
    except Exception:
        return 0


def _recorte(dias_padrao=30):
    try:
        dias = int(request.args.get('dias', dias_padrao))
    except (TypeError, ValueError):
        dias = dias_padrao
    dias = max(1, min(dias, 730))
    return dias, (datetime.now(timezone.utc) - timedelta(days=dias)).isoformat()


def _mediana(valores):
    if not valores:
        return 0
    v = sorted(valores)
    meio = len(v) // 2
    return v[meio] if len(v) % 2 else (v[meio - 1] + v[meio]) / 2


# ============================================================
# MOTOR DE FLUXOS
#
# As rotas não conhecem regra nenhuma: elas anunciam o que
# aconteceu, e o despachante decide o que fazer. Fluxo novo
# vira linha em `fluxo_regras`, não código espalhado.
# ============================================================

# Papéis operacionais por quadro. Vivem no código porque são a lista
# real do que o motor sabe fazer — crescem quando um fluxo precisa.
PAPEIS_QUADRO = [
    ('direciona', 'Direciona os projetos',
     'Recebe o aviso e escolhe quem fica com cada card novo'),
    ('cobranca', 'Recebe as cobranças',
     'Fica com o card de faturamento dos contratos deste quadro'),
    ('relacionamento', 'Conduz o relacionamento',
     'Aplica a pesquisa de satisfação depois da entrega'),
]
PAPEIS_VALIDOS = {p for p, _, _ in PAPEIS_QUADRO}

# Quadro de destino sugerido por produto. O closer confirma ou troca.
PRODUTO_QUADRO = {
    'Recrutamento e Seleção': 'recrutamento',
    'RH Estratégico': 'rhestrategico',
    'CX Data': 'cxdata',
    'Consultoria': 'projetos',
    'Treinamento': 'projetos',
    'Outro': 'projetos',
}
# Área correspondente a cada quadro, que é o que `projetos.area` guarda.
# ============================================================
# ÁRVORE DE QUADROS
#
# Dez famílias, dezoito quadros. A família é o que aparece na
# barra lateral e o que carrega permissão e responsabilidade;
# a subdivisão é aba dentro da tela.
#
# 'produto' separa o que o cliente compra do que sustenta a casa:
# é o que permite medir horas faturáveis e impedir que um contrato
# caia num quadro interno por engano.
# ============================================================
ARVORE_QUADROS = [
    # chave           área (projetos.area)      produto  ícone        subdivisões
    ('recrutamento',  'Recrutamento e seleção',  True,  'group_add', []),
    ('rhestrategico', 'RH Estratégico',          True,  'insights', [
        ('mensalista', 'Mensalista', 'Acompanhamento contínuo'),
        ('pccs',       'PCCS',       'Plano de Cargos, Carreiras e Salários'),
        ('pco',        'PCO',        'Pesquisa de Clima Organizacional'),
        ('gd',         'GD',         'Gestão de Desempenho'),
    ]),
    ('educacao',      'Educação',                True,  'school', [
        ('reaprendendo',  'Reaprendendo',  'Programa de formação'),
        ('liderar',       'Liderar',       'Programa de liderança'),
        ('personalizado', 'Personalizado', 'Programa sob medida'),
    ]),
    ('cxdata',        'CX Data',                 True,  'database', [
        ('pontual',    'Pontual',    'Entrega única'),
        ('mensalista', 'Mensalista', 'Acompanhamento contínuo'),
    ]),
    ('projetos',      'Projetos',                True,  'folder', []),

    ('comercial',     'Comercial',               False, 'handshake', []),
    ('marketing',     'Marketing',               False, 'campaign', []),
    # 'Adm/Fin' é o valor que os cards já existentes usam. Gravar
    # 'Financeiro' criava card invisível: nasce certo, some da tela.
    ('financeiro',    'Adm/Fin',                 False, 'payments', []),
    ('tecnologia',    'Tecnologia',              False, 'terminal', []),
    ('rhinterno',     'RH Interno',              False, 'badge', [
        ('endomarketing', 'Endomarketing', 'Comunicação e engajamento'),
        ('admissao',      'Admissão',      'Entrada de pessoas'),
        ('demissao',      'Demissão',      'Saída de pessoas'),
    ]),
]

QUADRO_AREA = {c: a for c, a, _, _, _ in ARVORE_QUADROS}
QUADROS_PRODUTO = [c for c, _, p, _, _ in ARVORE_QUADROS if p]
QUADROS_INTERNOS = [c for c, _, p, _, _ in ARVORE_QUADROS if not p]
SUBQUADROS = {c: [s[0] for s in subs] for c, _, _, _, subs in ARVORE_QUADROS if subs}
# Onde o card cai quando ninguém escolheu subdivisão: a primeira da lista.
SUB_PADRAO = {c: subs[0][0] for c, _, _, _, subs in ARVORE_QUADROS if subs}


# A lista de quadros das telas de acesso vem da árvore, não de uma
# cópia manual: duas fontes divergem no primeiro quadro novo.
QUADROS[:] = [(chave, area) for chave, area, _, _, _ in ARVORE_QUADROS]


def sub_valida(quadro, sub):
    """True se a subdivisão pertence ao quadro. Sem sub também é válido."""
    if not sub:
        return True
    return sub in SUBQUADROS.get(quadro, [])
FASE_ENTRADA = 'Backlog'


def responsavel_do_quadro(quadro, papel):
    """Quem exerce um papel operacional num quadro. None se ninguém."""
    try:
        r = (supabase.table("quadro_responsaveis")
             .select("usuario_id").eq("quadro", quadro).eq("papel", papel)
             .limit(1).execute())
        if r.data and r.data[0].get("usuario_id"):
            u = (supabase.table("usuarios").select("id, nome")
                 .eq("id", r.data[0]["usuario_id"]).limit(1).execute())
            if u.data:
                return u.data[0]
    except Exception as e:
        print("Aviso: responsavel_do_quadro:", e)
    return None


def _condicao_bate(condicao, dados):
    """Testa a condição da regra contra os dados do evento."""
    for chave, esperado in (condicao or {}).items():
        valor = dados.get(chave)
        if isinstance(esperado, list):
            if valor not in esperado:
                return False
        elif valor != esperado:
            return False
    return True


def disparar(evento, dados):
    """Anuncia um evento e executa as regras que casam com ele.

    Falha de regra nunca desfaz o que o usuário fez: fica registrada
    em `fluxo_execucoes` para alguém resolver depois.
    """
    resultados = []
    try:
        r = (supabase.table("fluxo_regras").select("*")
             .eq("evento", evento).eq("ativo", True).order("ordem").execute())
        regras = r.data or []
    except Exception as e:
        print(f"ERRO: nao foi possivel ler fluxo_regras para '{evento}':", e)
        _registrar_execucao(None, evento, dados, None,
                            f"fluxo_regras indisponivel: {str(e)[:300]}")
        return resultados

    # Zero regras não é normal quando o evento existe no desenho do fluxo.
    # Registrar aqui evita o ponto cego: sem isso, um contrato fechado
    # que não abre quadro nenhum não deixa rastro em lugar algum.
    if not regras:
        print(f"AVISO: nenhuma regra ativa para o evento '{evento}'. "
              f"Confira se fluxo.sql rodou e se o RLS libera leitura.")
        _registrar_execucao(None, evento, dados, None,
                            "nenhuma regra ativa encontrada para este evento")
        return resultados

    for regra in regras:
        if not _condicao_bate(regra.get("condicao"), dados):
            continue
        for acao in (regra.get("acoes") or []):
            tipo = acao.get("tipo")
            try:
                fn = ACOES.get(tipo)
                if not fn:
                    raise ValueError(f"ação desconhecida: {tipo}")
                res = fn(acao, dados)
                resultados.append({"regra": regra["nome"], "acao": tipo, "resultado": res})
                _registrar_execucao(regra, evento, dados, res, None)
            except Exception as e:
                print(f"Erro na regra '{regra.get('nome')}' ({tipo}):", e)
                _registrar_execucao(regra, evento, dados, None, str(e)[:400])
    return resultados


def _registrar_execucao(regra, evento, dados, resultado, erro):
    """Guarda o que o motor tentou. `regra` pode vir None quando a
    falha acontece antes de haver regra: é justamente esse o caso que
    não deixava rastro nenhum."""
    try:
        supabase.table("fluxo_execucoes").insert({
            "regra_id": (regra or {}).get("id"),
            "evento": evento,
            "gatilho_id": str(dados.get("lead_id") or dados.get("projeto_id") or ''),
            "resultado": resultado,
            "erro": erro,
        }).execute()
    except Exception as e:
        print("Aviso: fluxo_execucoes:", e)


# ---------- ações que o motor sabe executar ----------

def _acao_criar_lead(acao, dados):
    """Cria um lead novo ligado ao anterior.

    Novo e não reaproveitado: um cliente que fecha três vezes precisa
    virar três leads, senão a taxa de conversão fica errada.
    """
    if acao.get("funil") == "relacionamento" and not dados.get("com_relacionamento"):
        return {"pulado": "relacionamento nao marcado por quem finalizou"}
    novo = {
        "lead": dados.get("cliente_nome") or dados.get("lead_nome"),
        "empresa": dados.get("cliente_nome") or dados.get("empresa"),
        "funil": acao.get("funil", "relacionamento"),
        "coluna": acao.get("coluna", FASE_ENTRADA),
        "origem": "Cliente da casa",
        "produto": dados.get("produto"),
        "lead_pai_id": dados.get("lead_id"),
        "cliente_id": dados.get("cliente_id"),
        "contatos": 0,
        "movido_em": datetime.now(timezone.utc).isoformat(),
    }
    quadro = dados.get("quadro")
    if quadro:
        resp = responsavel_do_quadro(quadro, "relacionamento")
        if resp:
            novo["responsavel"] = resp.get("nome")
    for c in ("telefone", "email", "cnpj"):
        if dados.get(c):
            novo[c] = dados[c]
    r = supabase.table("leads").insert(novo).execute()
    return {"lead_id": (r.data or [{}])[0].get("id")}


def _acao_mover_lead(acao, dados):
    """Move o lead para outro funil e coluna."""
    lead_id = dados.get("lead_id")
    if not lead_id:
        raise ValueError("sem lead_id")
    destino_funil = acao.get("funil", "fechamento")
    destino_coluna = acao.get("coluna", "Agendamento")
    supabase.table("leads").update({
        "funil": destino_funil, "coluna": destino_coluna, "contatos": 0,
        "movido_em": datetime.now(timezone.utc).isoformat(),
    }).eq("id", lead_id).execute()
    try:
        supabase.table("lead_movimentos").insert({
            "lead_id": lead_id, "de_funil": dados.get("funil"),
            "de_coluna": dados.get("coluna"), "para_funil": destino_funil,
            "para_coluna": destino_coluna, "autor": "fluxo automático",
        }).execute()
    except Exception:
        pass
    return {"lead_id": lead_id, "funil": destino_funil, "coluna": destino_coluna}


def _acao_criar_cobranca(acao, dados):
    """Card de faturamento no Adm/Financeiro.

    Só roda se quem finalizou marcou a cobrança. Criar cobrança que
    ninguém pediu é pior que não criar nenhuma: alguém precisa
    descobrir e apagar.
    """
    if acao.get("etapa") == "entrega" and not dados.get("com_cobranca"):
        return {"pulado": "cobranca nao marcada por quem finalizou"}
    resp = responsavel_do_quadro('financeiro', 'cobranca')
    etapa = acao.get("etapa", "fechamento")
    rotulo = "Emitir NF e boleto" if etapa == "fechamento" else "Faturar entrega"
    novo = {
        "nome_projeto": f"{rotulo} · {dados.get('projeto_nome') or dados.get('cliente_nome') or 'contrato'}",
        "area": QUADRO_AREA['financeiro'],
        "status": FASE_ENTRADA,
        "empresa": dados.get("cliente_nome"),
        "cliente_id": dados.get("cliente_id"),
        "origem_lead_id": dados.get("lead_id"),
        "vinculado_a": dados.get("lote_id"),
        "valor": dados.get("valor"),
        "responsavel": resp.get("nome") if resp else None,
        "aguardando_responsavel": resp is None,
        "data_status_atual": datetime.now(timezone.utc).isoformat(),
    }
    r = supabase.table("projetos").insert(novo).execute()
    return {"projeto_id": (r.data or [{}])[0].get("id"), "responsavel": novo["responsavel"]}


# Colunas que dependem de um SQL ter rodado. Se faltar alguma, o card
# ainda precisa nascer: perder um contrato fechado por causa de coluna
# ausente é pior que criar o card sem o dado extra.
_COLUNAS_OPCIONAIS = ("subquadro", "origem_lead_id", "lote_id", "lote_pos",
                      "lote_total", "aguardando_responsavel", "vinculado_a")


def _inserir_projeto(novo):
    """Insere o projeto e, se o banco recusar por coluna inexistente,
    tenta de novo sem os campos opcionais, avisando no log."""
    try:
        return supabase.table("projetos").insert(novo).execute()
    except Exception as e:
        msg = str(e)
        faltando = [c for c in _COLUNAS_OPCIONAIS if c in msg and c in novo]
        if not faltando:
            raise
        print(f"Aviso: coluna(s) {faltando} nao existem em projetos. "
              f"Rode quadros.sql e fluxo.sql. Criando o card sem elas.")
        reduzido = {k: v for k, v in novo.items() if k not in faltando}
        return supabase.table("projetos").insert(reduzido).execute()


MODOS_QUADRO = ('direto', 'fila', 'rodizio')


def config_do_quadro(quadro):
    """Como o quadro distribui os cards que chegam.

    Sem registro, responde 'fila': é o comportamento atual, então
    quadro não configurado continua funcionando como antes.
    """
    try:
        r = (supabase.table("quadro_config").select("modo")
             .eq("quadro", quadro).limit(1).execute())
        if r.data and r.data[0].get("modo") in MODOS_QUADRO:
            return r.data[0]["modo"]
    except Exception as e:
        print("Aviso: quadro_config indisponivel:", e)
    return 'fila'


def executores_do_quadro(quadro):
    """Quem pode receber card deste quadro, com nome resolvido."""
    try:
        r = (supabase.table("quadro_executores").select("usuario_id")
             .eq("quadro", quadro).execute())
        ids = [x["usuario_id"] for x in (r.data or []) if x.get("usuario_id")]
        if not ids:
            return []
        u = (supabase.table("usuarios").select("id, nome, ativo")
             .in_("id", ids).execute())
        return [x for x in (u.data or []) if x.get("ativo") is not False]
    except Exception as e:
        print("Aviso: executores_do_quadro:", e)
        return []


def escolher_por_rodizio(quadro):
    """Quem tem menos cards em aberto neste quadro.

    Empate resolve pelo primeiro da lista, que é estável: o
    critério não pode variar entre duas chamadas seguidas.
    """
    pessoas = executores_do_quadro(quadro)
    if not pessoas:
        return None
    area = QUADRO_AREA.get(quadro)
    carga = {p["nome"]: 0 for p in pessoas}
    try:
        r = (supabase.table("projetos").select("responsavel")
             .eq("area", area).is_("excluido_em", "null").execute())
        for p in (r.data or []):
            nome = p.get("responsavel")
            if nome in carga:
                carga[nome] += 1
    except Exception as e:
        print("Aviso: carga para rodizio:", e)
    return min(pessoas, key=lambda p: carga.get(p["nome"], 0))


def definir_dono(quadro):
    """Quem recebe o card novo, conforme o modo do quadro.

    Devolve (pessoa, aguardando). `aguardando` True significa que
    o card entra na fila de atribuicao.
    """
    modo = config_do_quadro(quadro)

    if modo == 'direto':
        # Quem recebe e escolhido em Configuracoes, entre os que foram
        # marcados como responsaveis em Acessos. Cair no "primeiro
        # cadastrado" fazia a escolha da tela nao valer nada.
        escolhido = executor_padrao_do_quadro(quadro)
        if escolhido:
            return escolhido, False
        pessoas = executores_do_quadro(quadro)
        if pessoas:
            return pessoas[0], False
        # Sem ninguem, o direcionador assume em vez de virar orfao.
        resp = responsavel_do_quadro(quadro, 'direciona')
        return resp, resp is None

    if modo == 'rodizio':
        p = escolher_por_rodizio(quadro)
        if p:
            return p, False
        resp = responsavel_do_quadro(quadro, 'direciona')
        return resp, resp is None

    # fila: o card espera alguem escolher
    return None, True


def executor_padrao_do_quadro(quadro):
    """A pessoa escolhida em Configuracoes para o modo Direto.

    Devolve None quando nao ha escolha, quando a pessoa foi desativada
    ou quando ela perdeu a marcacao de responsavel em Acessos -- nesses
    casos `definir_dono` cai no plano seguinte em vez de atribuir card
    a quem nao deveria recebe-lo.
    """
    try:
        c = (supabase.table("quadro_config").select("executor_padrao")
             .eq("quadro", quadro).limit(1).execute())
        uid = (c.data or [{}])[0].get("executor_padrao")
        if not uid:
            return None
        marcado = (supabase.table("quadro_executores").select("id")
                   .eq("quadro", quadro).eq("usuario_id", uid).limit(1).execute())
        if not marcado.data:
            return None
        u = (supabase.table("usuarios").select("id, nome, ativo")
             .eq("id", uid).limit(1).execute())
        pessoa = (u.data or [None])[0]
        if pessoa and pessoa.get("ativo") is not False:
            return pessoa
    except Exception as e:
        print("Aviso: executor_padrao_do_quadro:", e)
    return None


def _acao_abrir_quadros(acao, dados):
    """Cria os cards nos quadros escolhidos na janela de fechamento.

    A escolha vem do closer, não de um mapa fixo: assim qualquer
    produto futuro funciona sem mudar código.
    """
    criados = []
    for pedido in (dados.get("quadros") or []):
        quadro = pedido.get("quadro")
        if quadro not in QUADRO_AREA:
            continue
        # A quantidade vem no nível de cima do pedido, não dentro de cada
        # quadro. Ler só de dentro fazia todo contrato virar 1 card,
        # mesmo quando a janela pedia 5.
        qtd = max(1, min(int(pedido.get("quantidade") or dados.get("quantidade") or 1), 50))
        # Subdivisão escolhida na janela; se vier inválida ou vazia,
        # cai na padrão da família em vez de ficar sem lugar.
        sub = pedido.get("sub")
        if not sub_valida(quadro, sub):
            sub = None
        if not sub:
            sub = SUB_PADRAO.get(quadro)
        if quadro == 'financeiro':
            criados.append(_acao_criar_cobranca({"etapa": "fechamento"}, dados))
            continue
        # Quem fica com o card depende do modo do quadro: em Direto e
        # Rodízio ele já nasce com dono; em Fila, espera atribuição.
        dono, aguardando = definir_dono(quadro)
        direciona = responsavel_do_quadro(quadro, 'direciona')
        lote = str(uuid.uuid4()) if qtd > 1 else None
        for i in range(qtd):
            nome = dados.get("projeto_nome") or dados.get("cliente_nome") or "Novo projeto"
            if qtd > 1:
                nome = f"{nome} ({i+1}/{qtd})"
            novo = {
                "nome_projeto": nome,
                "area": QUADRO_AREA[quadro],
                "subquadro": sub,
                "status": FASE_ENTRADA,
                "empresa": dados.get("cliente_nome"),
                "cliente_id": dados.get("cliente_id"),
                "origem_lead_id": dados.get("lead_id"),
                "lote_id": lote,
                "lote_pos": (i + 1) if qtd > 1 else None,
                "lote_total": qtd if qtd > 1 else None,
                "valor": dados.get("valor") if i == 0 else None,
                "responsavel": dono.get("nome") if dono else None,
                "aguardando_responsavel": aguardando,
                "data_status_atual": datetime.now(timezone.utc).isoformat(),
            }
            r = _inserir_projeto(novo)
            criados.append({
                "projeto_id": (r.data or [{}])[0].get("id"),
                "quadro": quadro,
                "responsavel": dono.get("nome") if dono else None,
                # Em Direto e Rodízio avisa quem executa; em Fila, quem
                # direciona. Card que nasce sem ninguém saber é o
                # problema que estamos resolvendo.
                "avisar": (dono or direciona or {}).get("nome"),
            })
    return {"criados": len(criados), "itens": criados}


ACOES = {
    "criar_lead": _acao_criar_lead,
    "mover_lead": _acao_mover_lead,
    "criar_cobranca": _acao_criar_cobranca,
    "abrir_quadros": _acao_abrir_quadros,
}


@app.route('/api/fluxo/fechar-lead/<lead_id>', methods=['POST'])
def fechar_lead(lead_id):
    """Fecha o contrato: move o lead para Ganho e abre os quadros escolhidos."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        d = request.json or {}
        r = supabase.table("leads").select("*").eq("id", lead_id).limit(1).execute()
        if not r.data:
            return jsonify({"status": "erro", "mensagem": "Lead não encontrado."}), 404
        lead = r.data[0]

        cliente_id = d.get("cliente_id") or lead.get("cliente_id")
        cliente_nome = d.get("cliente_nome") or lead.get("empresa") or lead.get("lead")

        # Cliente novo criado na hora, já ligado ao lead de origem.
        if not cliente_id and d.get("criar_cliente"):
            rc = supabase.table("clientes").insert({
                "nome_empresa": cliente_nome,
                "cnpj": d.get("cnpj") or lead.get("cnpj"),
                "email": lead.get("email"),
                "telefone": lead.get("telefone"),
                "lead_id": lead_id,
                "ativo": True,
            }).execute()
            cliente_id = (rc.data or [{}])[0].get("id")

        atual_funil, atual_coluna = lead.get("funil"), lead.get("coluna")
        supabase.table("leads").update({
            "funil": "fechamento", "coluna": "Ganho", "cliente_id": cliente_id,
            "valor_estimado": d.get("valor") or lead.get("valor_estimado"),
            "movido_em": datetime.now(timezone.utc).isoformat(),
        }).eq("id", lead_id).execute()

        try:
            supabase.table("lead_movimentos").insert({
                "lead_id": lead_id, "de_funil": atual_funil, "de_coluna": atual_coluna,
                "para_funil": "fechamento", "para_coluna": "Ganho",
                "autor": session.get('usuario_nome'),
            }).execute()
        except Exception:
            pass

        resultado = disparar('lead.ganho', {
            "lead_id": lead_id, "funil": "fechamento",
            "lead_nome": lead.get("lead"),
            "cliente_id": cliente_id, "cliente_nome": cliente_nome,
            "produto": d.get("produto") or lead.get("produto"),
            "projeto_nome": d.get("projeto_nome") or lead.get("produto"),
            "valor": d.get("valor") or lead.get("valor_estimado"),
            "quadros": d.get("quadros") or [],
            "telefone": lead.get("telefone"), "email": lead.get("email"),
            "cnpj": d.get("cnpj") or lead.get("cnpj"),
        })
        return jsonify({"status": "sucesso", "cliente_id": cliente_id, "fluxo": resultado}), 200
    except Exception as e:
        print("Erro em fechar_lead:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao fechar o contrato.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/quadros/fila', methods=['GET'])
def fila_atribuicao():
    """Cards esperando responsável, com quem pode recebê-los.

    Filtra por quadro quando informado: a fila aparece dentro do
    quadro, e mostrar card de outra área ali confundiria.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not (pode('projeto.atribuir') or session.get('nivel_acesso') in ('admin', 'gestor')):
        return jsonify({"status": "sucesso", "projetos": [], "pessoas": []}), 200
    try:
        quadro = request.args.get('quadro')
        q = (supabase.table("projetos").select("*")
             .eq("aguardando_responsavel", True).is_("excluido_em", "null"))
        if quadro and quadro in QUADRO_AREA:
            q = q.eq("area", QUADRO_AREA[quadro])
        r = q.order("criado_em").execute()
        itens = filtrar_projetos_permitidos(r.data or [])

        pessoas = []
        if quadro:
            pessoas = [{"id": str(p["id"]), "nome": p.get("nome")}
                       for p in executores_do_quadro(quadro)]
        return jsonify({"status": "sucesso", "projetos": itens,
                        "pessoas": pessoas, "total": len(itens)}), 200
    except Exception as e:
        print("Erro em fila_atribuicao:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar a fila.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/quadros/config', methods=['GET'])
def listar_config_quadros():
    """Como cada quadro distribui, quem direciona e quem executa."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        modos, resp, execs, carga = {}, {}, {}, {}
        try:
            for c in ((supabase.table("quadro_config").select("*").execute()).data or []):
                modos[c["quadro"]] = c.get("modo") or 'fila'
        except Exception as e:
            print("Aviso: quadro_config:", e)
        try:
            for r in ((supabase.table("quadro_responsaveis").select("*").execute()).data or []):
                resp.setdefault(r["quadro"], {})[r["papel"]] = str(r.get("usuario_id") or '')
        except Exception as e:
            print("Aviso: quadro_responsaveis:", e)
        try:
            for e_ in ((supabase.table("quadro_executores").select("*").execute()).data or []):
                execs.setdefault(e_["quadro"], []).append(str(e_.get("usuario_id") or ''))
        except Exception as e:
            print("Aviso: quadro_executores:", e)

        # Cards em aberto e esperando dono, por área.
        try:
            r = (supabase.table("projetos")
                 .select("area, status, aguardando_responsavel")
                 .is_("excluido_em", "null").execute())
            for p in (r.data or []):
                a = p.get("area")
                if p.get("status") in ('Finalizado', 'Cancelado'):
                    continue
                d_ = carga.setdefault(a, {"abertos": 0, "esperando": 0})
                d_["abertos"] += 1
                if p.get("aguardando_responsavel"):
                    d_["esperando"] += 1
        except Exception as e:
            print("Aviso: carga dos quadros:", e)

        pessoas = (supabase.table("usuarios")
                   .select("id, nome, quadros, ativo, tipo_usuario").execute()).data or []
        internos = [p for p in pessoas
                    if p.get("ativo") is not False
                    and (p.get("tipo_usuario") or 'interno') == 'interno']

        saida = []
        for chave, area, produto, icone, subs in ARVORE_QUADROS:
            c = carga.get(area, {})
            # Só quem tem o quadro liberado pode receber card dele:
            # atribuir a quem não consegue abrir o quadro é confusão
            # silenciosa.
            elegiveis = [{"id": str(p["id"]), "nome": p.get("nome")}
                         for p in internos if chave in (p.get("quadros") or [])]
            saida.append({
                "chave": chave, "nome": area, "produto": produto, "icone": icone,
                "modo": modos.get(chave, 'fila'),
                "direciona": resp.get(chave, {}).get("direciona") or None,
                "cobranca": resp.get(chave, {}).get("cobranca") or None,
                "executores": execs.get(chave, []),
                "elegiveis": elegiveis,
                "abertos": c.get("abertos", 0),
                "esperando": c.get("esperando", 0),
            })
        return jsonify({"status": "sucesso", "quadros": saida,
                        "pessoas": [{"id": str(p["id"]), "nome": p.get("nome")}
                                    for p in internos]}), 200
    except Exception as e:
        print("Erro em listar_config_quadros:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/quadros/config/<quadro>', methods=['PUT'])
def salvar_config_quadro(quadro):
    """Grava modo, direcionador, cobrança e executores de um quadro."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    if quadro not in QUADRO_AREA:
        return jsonify({"status": "erro", "mensagem": "Quadro inválido."}), 400
    try:
        d = request.json or {}
        modo = d.get("modo")
        if modo not in MODOS_QUADRO:
            return jsonify({"status": "erro", "mensagem": "Modo inválido."}), 400

        executores = [str(x) for x in (d.get("executores") or []) if x]
        # Direto com vários executores é ambíguo: quem receberia?
        if modo == 'direto' and len(executores) > 1:
            return jsonify({"status": "erro",
                            "mensagem": "No modo Direto, escolha uma pessoa só."}), 400
        if modo == 'direto' and not executores:
            return jsonify({"status": "erro",
                            "mensagem": "No modo Direto, escolha quem recebe os cards."}), 400
        if modo == 'fila' and not d.get("direciona"):
            return jsonify({"status": "erro",
                            "mensagem": "No modo Fila, escolha quem direciona."}), 400
        if modo == 'rodizio' and len(executores) < 2:
            return jsonify({"status": "erro",
                            "mensagem": "O rodízio precisa de pelo menos duas pessoas."}), 400

        supabase.table("quadro_config").upsert({
            "quadro": quadro, "modo": modo,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
            "atualizado_por": session.get('usuario_nome'),
        }).execute()

        for papel in ("direciona", "cobranca"):
            if papel not in d:
                continue
            valor = d.get(papel) or None
            supabase.table("quadro_responsaveis").upsert({
                "quadro": quadro, "papel": papel, "usuario_id": valor,
                "atualizado_em": datetime.now(timezone.utc).isoformat(),
            }, on_conflict="quadro,papel").execute()

        if "executores" in d:
            supabase.table("quadro_executores").delete().eq("quadro", quadro).execute()
            if executores:
                supabase.table("quadro_executores").insert(
                    [{"quadro": quadro, "usuario_id": u} for u in executores]).execute()

        registrar_auditoria('quadro_configurado', 'quadro', quadro,
                            {"modo": modo, "executores": len(executores)})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em salvar_config_quadro:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/modelos', methods=['GET'])
def listar_modelos():
    """Modelos de acesso e quantas pessoas usam cada um."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        modelos = (supabase.table("modelos_acesso").select("*")
                   .order("nome").execute()).data or []
        pessoas = (supabase.table("usuarios")
                   .select("id, modelo_id, papel_id, quadros, areas").execute()).data or []
        for m in modelos:
            usam = [p for p in pessoas if str(p.get("modelo_id") or '') == str(m["id"])]
            m["pessoas"] = len(usam)
            # Divergência: quem veio do modelo mas já não bate com ele.
            # Distinguir exceção deliberada de configuração esquecida.
            divergentes = 0
            for p in usam:
                if (str(p.get("papel_id") or '') != str(m.get("papel_id") or '')
                        or sorted(p.get("quadros") or []) != sorted(m.get("quadros") or [])
                        or sorted(p.get("areas") or []) != sorted(m.get("areas") or [])):
                    divergentes += 1
            m["divergentes"] = divergentes
        return jsonify({"status": "sucesso", "modelos": modelos}), 200
    except Exception as e:
        print("Erro em listar_modelos:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar modelos.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/modelos/<modelo_id>/aplicar', methods=['POST'])
def aplicar_modelo(modelo_id):
    """Aplica um modelo a uma ou mais pessoas.

    Substitui nível, quadros e áreas. Não mexe em ajustes
    individuais: eles são exceções deliberadas.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        alvos = (request.json or {}).get("usuarios") or []
        if not alvos:
            return jsonify({"status": "erro", "mensagem": "Escolha ao menos uma pessoa."}), 400
        r = (supabase.table("modelos_acesso").select("*")
             .eq("id", modelo_id).limit(1).execute())
        if not r.data:
            return jsonify({"status": "erro", "mensagem": "Modelo não encontrado."}), 404
        m = r.data[0]

        upd = {
            "papel_id": m.get("papel_id"),
            "quadros": m.get("quadros") or [],
            "areas": m.get("areas") or [],
            "modelo_id": modelo_id,
        }
        feitos = 0
        for uid in alvos:
            try:
                supabase.table("usuarios").update(upd).eq("id", uid).execute()
                feitos += 1
            except Exception as e:
                print(f"Erro ao aplicar modelo em {uid}:", e)
        registrar_auditoria('modelo_aplicado', 'modelo', modelo_id,
                            {"nome": m.get("nome"), "pessoas": feitos})
        return jsonify({"status": "sucesso", "feitos": feitos}), 200
    except Exception as e:
        print("Erro em aplicar_modelo:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao aplicar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/responsaveis', methods=['GET'])
def listar_responsaveis():
    """Papéis operacionais de cada quadro."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not (pode('papel.gerir') or session.get('nivel_acesso') == 'admin'):
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        r = supabase.table("quadro_responsaveis").select("*").execute()
        mapa = {}
        for item in (r.data or []):
            mapa.setdefault(item["quadro"], {})[item["papel"]] = item.get("usuario_id")
        pessoas = (supabase.table("usuarios")
                   .select("id, nome, email, ativo, tipo_usuario")
                   .order("nome").execute()).data or []
        return jsonify({
            "status": "sucesso",
            "quadros": [{"chave": c, "nome": n} for c, n in QUADROS],
            "papeis": [{"chave": c, "nome": n, "descricao": dd} for c, n, dd in PAPEIS_QUADRO],
            "definidos": mapa,
            "pessoas": [p for p in pessoas
                        if p.get("ativo") is not False
                        and (p.get("tipo_usuario") or 'interno') != 'externo'],
        }), 200
    except Exception as e:
        print("Erro em listar_responsaveis:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/responsaveis', methods=['PUT'])
def definir_responsavel():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not (pode('papel.gerir') or session.get('nivel_acesso') == 'admin'):
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.json or {}
        quadro, papel = d.get("quadro"), d.get("papel")
        if quadro not in QUADROS_VALIDOS or papel not in PAPEIS_VALIDOS:
            return jsonify({"status": "erro", "mensagem": "Quadro ou papel inválido."}), 400
        usuario_id = d.get("usuario_id") or None
        supabase.table("quadro_responsaveis").upsert({
            "quadro": quadro, "papel": papel, "usuario_id": usuario_id,
            "atualizado_em": datetime.now(timezone.utc).isoformat(),
        }, on_conflict="quadro,papel").execute()
        registrar('responsavel_definido', 'quadro', quadro,
                            {"papel": papel, "usuario_id": usuario_id})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em definir_responsavel:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/projetos/aguardando', methods=['GET'])
def projetos_aguardando():
    """Cards criados pelo fluxo que ainda não têm responsável."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        r = (supabase.table("projetos").select("*")
             .eq("aguardando_responsavel", True).is_("excluido_em", "null")
             .order("criado_em", desc=True).execute())
        itens = filtrar_projetos_permitidos(r.data or [])
        return jsonify({"status": "sucesso", "projetos": itens, "total": len(itens)}), 200
    except Exception as e:
        print("Erro em projetos_aguardando:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/projetos/<projeto_id>/atribuir', methods=['POST'])
def atribuir_projeto(projeto_id):
    """Define o responsável. Com `lote`, vale para todos os cards do contrato."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not (pode('projeto.atribuir') or session.get('nivel_acesso') in ('admin', 'gestor')):
        return jsonify({"status": "erro",
                        "mensagem": "Você não tem permissão para atribuir projetos."}), 403
    try:
        d = request.json or {}
        responsavel = (d.get("responsavel") or '').strip()
        if not responsavel:
            return jsonify({"status": "erro", "mensagem": "Informe o responsável."}), 400

        upd = {"responsavel": responsavel, "aguardando_responsavel": False}
        if d.get("prazo"):
            upd["prazo_data"] = d["prazo"]

        r = supabase.table("projetos").select("lote_id").eq("id", projeto_id).limit(1).execute()
        if not r.data:
            return jsonify({"status": "erro", "mensagem": "Projeto não encontrado."}), 404
        lote = r.data[0].get("lote_id")

        if d.get("lote") and lote:
            res = (supabase.table("projetos").update(upd)
                   .eq("lote_id", lote).eq("aguardando_responsavel", True).execute())
            n = len(res.data or [])
        else:
            supabase.table("projetos").update(upd).eq("id", projeto_id).execute()
            n = 1
        registrar('projeto_atribuido', 'projeto', projeto_id,
                            {"responsavel": responsavel, "quantidade": n})
        return jsonify({"status": "sucesso", "atribuidos": n}), 200
    except Exception as e:
        print("Erro em atribuir_projeto:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao atribuir.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/painel/operacao', methods=['GET'])
def painel_operacao():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        dias, desde = _recorte(30)
        hoje = datetime.now(timezone.utc).date().isoformat()

        todos = (supabase.table("projetos").select("*")
                 .is_("excluido_em", "null").execute()).data or []
        projetos = filtrar_projetos_permitidos(todos)

        quadro = request.args.get('quadro')
        if quadro:
            areas_do_quadro = [n for c, n in QUADROS if c == quadro]
            if areas_do_quadro:
                projetos = [p for p in projetos if p.get('area') == areas_do_quadro[0]]
        pessoa = request.args.get('pessoa')
        if pessoa:
            projetos = [p for p in projetos if (p.get('responsavel') or '') == pessoa]

        ativos = [p for p in projetos if p.get('status') not in STATUS_ENCERRADOS]
        concluidos = [p for p in projetos
                      if p.get('status') == 'Finalizado'
                      and str(p.get('data_conclusao') or '') >= desde]

        # --- o que precisa de atenção ---
        atrasados, vencendo = [], []
        for p in ativos:
            prazo = str(p.get('prazo_data') or '')[:10]
            if not prazo:
                continue
            if prazo < hoje:
                atrasados.append({
                    "id": p.get('id'), "nome": p.get('nome_projeto'),
                    "empresa": p.get('empresa'), "area": p.get('area'),
                    "status": p.get('status'), "responsavel": p.get('responsavel'),
                    "dias": (datetime.fromisoformat(hoje) - datetime.fromisoformat(prazo)).days,
                })
            elif (datetime.fromisoformat(prazo) - datetime.fromisoformat(hoje)).days <= 3:
                vencendo.append({
                    "id": p.get('id'), "nome": p.get('nome_projeto'),
                    "empresa": p.get('empresa'), "area": p.get('area'),
                    "status": p.get('status'), "responsavel": p.get('responsavel'),
                    "dias": (datetime.fromisoformat(prazo) - datetime.fromisoformat(hoje)).days,
                })
        atrasados.sort(key=lambda x: -x['dias'])

        parados = [p for p in ativos
                   if p.get('status') not in STATUS_PARADOS
                   and _dias_desde(p.get('data_status_atual')) > 14]

        # --- por área, dividido por tempo na fase ---
        por_area = {}
        for p in ativos:
            a = p.get('area') or 'Sem área'
            faixa = por_area.setdefault(a, {"area": a, "total": 0, "ok": 0, "atencao": 0, "critico": 0})
            faixa["total"] += 1
            d = _dias_desde(p.get('data_status_atual'))
            if d <= 7:
                faixa["ok"] += 1
            elif d <= 14:
                faixa["atencao"] += 1
            else:
                faixa["critico"] += 1
        areas = sorted(por_area.values(), key=lambda x: -x["total"])

        # --- carga por pessoa ---
        por_pessoa = {}
        for p in ativos:
            r = p.get('responsavel') or 'Sem responsável'
            por_pessoa[r] = por_pessoa.get(r, 0) + 1
        carga = sorted(({"pessoa": k, "total": v} for k, v in por_pessoa.items()),
                       key=lambda x: -x["total"])

        # --- tempo até concluir ---
        duracoes = []
        for p in concluidos:
            ini, fim = p.get('data_inicio') or p.get('criado_em'), p.get('data_conclusao')
            if ini and fim:
                try:
                    d0 = datetime.fromisoformat(str(ini).replace('Z', '+00:00'))
                    d1 = datetime.fromisoformat(str(fim).replace('Z', '+00:00'))
                    duracoes.append(max(0, (d1 - d0).days))
                except Exception:
                    pass

        # --- horas por área e fora do plano ---
        horas_area, horas_total, fora_plano = {}, 0, 0
        try:
            logs = (supabase.table("time_logs").select("*")
                    .gte("criado_em", desde).execute()).data or []
            mapa_area = {str(p.get('id')): p.get('area') for p in projetos}
            permitidos = set(mapa_area.keys())
            for l in logs:
                pid = str(l.get('projeto_id') or '')
                if pid not in permitidos:
                    continue
                seg = l.get('tempo_segundos') or 0
                h = seg / 3600.0
                horas_total += h
                a = mapa_area.get(pid) or 'Sem área'
                horas_area[a] = horas_area.get(a, 0) + h
                if not l.get('planejamento_id'):
                    fora_plano += h
        except Exception as e:
            print("Aviso: time_logs indisponivel no painel:", e)

        # --- gargalo por fase ---
        gargalo = []
        try:
            movs = (supabase.table("projeto_movimentos").select("*")
                    .order("projeto_id").order("criado_em").execute()).data or []
            area_filtro = areas[0]["area"] if areas else None
            if quadro:
                nomes = [n for c, n in QUADROS if c == quadro]
                area_filtro = nomes[0] if nomes else area_filtro
            duracao_fase = {}
            anterior = {}
            for m in movs:
                if area_filtro and m.get('area') != area_filtro:
                    continue
                pid = str(m.get('projeto_id'))
                ant = anterior.get(pid)
                if ant:
                    try:
                        d0 = datetime.fromisoformat(str(ant['criado_em']).replace('Z', '+00:00'))
                        d1 = datetime.fromisoformat(str(m['criado_em']).replace('Z', '+00:00'))
                        fase = ant['para_status']
                        duracao_fase.setdefault(fase, []).append(max(0, (d1 - d0).days))
                    except Exception:
                        pass
                anterior[pid] = m
            gargalo = [{"fase": f, "dias": round(_mediana(v), 1), "amostra": len(v)}
                       for f, v in duracao_fase.items()]
            gargalo.sort(key=lambda x: -x["dias"])
        except Exception as e:
            print("Aviso: projeto_movimentos indisponivel:", e)

        # --- clientes com mais trabalho aberto ---
        por_cliente = {}
        for p in ativos:
            c = p.get('empresa') or 'Sem cliente'
            item = por_cliente.setdefault(c, {"cliente": c, "projetos": 0, "areas": set(), "prazo": None})
            item["projetos"] += 1
            if p.get('area'):
                item["areas"].add(p['area'])
            prazo = str(p.get('prazo_data') or '')[:10]
            if prazo and (item["prazo"] is None or prazo < item["prazo"]):
                item["prazo"] = prazo
        clientes = sorted(por_cliente.values(), key=lambda x: -x["projetos"])[:6]
        for c in clientes:
            c["areas"] = sorted(c["areas"])

        return jsonify({
            "status": "sucesso",
            "periodo_dias": dias,
            "kpis": {
                "ativos": len(ativos),
                "concluidos": len(concluidos),
                "atrasados": len(atrasados),
                "mediana_conclusao": round(_mediana(duracoes)),
                "horas": round(horas_total),
                "fora_plano_pct": round(fora_plano / horas_total * 100) if horas_total else 0,
            },
            "atencao": {
                "atrasados": atrasados[:6],
                "vencendo": vencendo[:4],
                "parados": len(parados),
            },
            "areas": areas,
            "carga": carga,
            "gargalo": gargalo[:8],
            "horas_area": sorted(({"area": k, "horas": round(v)} for k, v in horas_area.items()),
                                 key=lambda x: -x["horas"]),
            "fora_plano_horas": round(fora_plano),
            "clientes": clientes,
        }), 200
    except Exception as e:
        print("Erro em painel_operacao:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao montar o painel.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/painel/comercial', methods=['GET'])
def painel_comercial():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        dias, desde = _recorte(90)          # 90 dias: o ciclo de venda é de ~38
        hoje = datetime.now(timezone.utc).date().isoformat()
        ver_valor = pode('crm.valor.ver') or session.get('nivel_acesso') in ('admin', 'gestor')

        leads = (supabase.table("leads").select("*")
                 .is_("excluido_em", "null").execute()).data or []
        movs = (supabase.table("lead_movimentos").select("*")
                .gte("criado_em", desde).execute()).data or []

        # Escopo: quem só vê os próprios leads também só vê os próprios números.
        esc = caps_da_sessao().get('crm.lead.ver')
        if esc == 'proprio':
            eu = (session.get('usuario_nome') or '').strip().lower()
            leads = [l for l in leads if (l.get('responsavel') or '').strip().lower() == eu]
        pessoa = request.args.get('pessoa')
        if pessoa:
            leads = [l for l in leads if (l.get('responsavel') or '') == pessoa]
        ids_visiveis = {str(l['id']) for l in leads}
        movs = [m for m in movs if str(m.get('lead_id')) in ids_visiveis]

        def valor(l):
            try:
                return float(l.get('valor_estimado') or 0)
            except (TypeError, ValueError):
                return 0.0

        ativos = [l for l in leads if l.get('coluna') not in ('Ganho', 'Perdido')]
        ganhos = [l for l in leads if l.get('coluna') == 'Ganho'
                  and str(l.get('movido_em') or '')[:10] >= desde[:10]]
        perdidos = [l for l in leads if l.get('coluna') == 'Perdido'
                    and str(l.get('movido_em') or '')[:10] >= desde[:10]]
        nutricao = [l for l in leads if l.get('funil') == 'nutricao']

        # --- precisa de atenção ---
        contato_hoje = [l for l in ativos if str(l.get('proximo_contato') or '')[:10] <= hoje
                        and l.get('proximo_contato')]
        parados = [l for l in ativos if _dias_desde(l.get('movido_em') or l.get('criado_em')) > 14]
        sem_contato = [l for l in ativos if not l.get('proximo_contato')
                       and l.get('funil') == 'fechamento']

        # --- estoque: onde o dinheiro está parado ---
        estoque = {}
        for l in ativos:
            chave = (l.get('funil') or '?', l.get('coluna') or '?')
            it = estoque.setdefault(chave, {"funil": chave[0], "etapa": chave[1],
                                            "qtd": 0, "valor": 0.0})
            it["qtd"] += 1
            it["valor"] += valor(l)

        # --- FLUXO: quantos leads distintos passaram por cada etapa ---
        # É daqui que sai a taxa de conversão. Conta lead, não movimento:
        # quem voltou e passou de novo conta uma vez só.
        CASCATA = [
            ('qualificacao', 'Prospecção'), ('qualificacao', 'Contato'),
            ('qualificacao', 'Ganho'),
            ('fechamento', 'Agendamento'), ('fechamento', 'Proposta'),
            ('fechamento', 'Negociação'), ('fechamento', 'Fechamento'),
        ]
        passaram = {}
        for m in movs:
            chave = (m.get('para_funil'), m.get('para_coluna'))
            passaram.setdefault(chave, set()).add(str(m.get('lead_id')))
        # Leads que já estavam na etapa antes do recorte e seguem lá contam também.
        for l in ativos:
            chave = (l.get('funil'), l.get('coluna'))
            if chave in [c for c in CASCATA]:
                passaram.setdefault(chave, set()).add(str(l['id']))

        cascata = []
        topo = len(passaram.get(CASCATA[0], set())) or 1
        for i, chave in enumerate(CASCATA):
            qtd = len(passaram.get(chave, set()))
            prox = len(passaram.get(CASCATA[i + 1], set())) if i + 1 < len(CASCATA) else None
            cascata.append({
                "funil": chave[0], "etapa": chave[1], "qtd": qtd,
                "pct_topo": round(qtd / topo * 100, 1),
                "conversao": (round(prox / qtd * 100) if qtd and prox is not None else None),
                "sairam": (max(0, qtd - prox) if prox is not None else None),
            })

        # --- para onde foram os que saíram ---
        destino = {"nutricao": len(nutricao), "perdido": len(perdidos),
                   "ativos": len(ativos)}

        # --- objeções e motivos de perda ---
        # São coisas diferentes: objeção é "conversamos e ele disse não
        # agora"; perda é "não deu para falar". Misturar as duas faria
        # "contato não existe" competir com "preço" no mesmo gráfico.
        MOTIVOS_PERDA = ('contato_invalido', 'nao_localizado', 'empresa_fechada',
                         'duplicado', 'nao_e_publico', 'outra_perda')
        objecoes, perdas = {}, {}
        for m in movs:
            o = m.get('objecao')
            if not o:
                continue
            if o in MOTIVOS_PERDA or m.get('para_coluna') == 'Perdido':
                perdas[o] = perdas.get(o, 0) + 1
            else:
                objecoes[o] = objecoes.get(o, 0) + 1

        # --- origem que converte ---
        por_origem = {}
        for l in leads:
            o = l.get('origem') or 'Não informada'
            it = por_origem.setdefault(o, {"origem": o, "total": 0, "ganhos": 0})
            it["total"] += 1
            if l.get('coluna') == 'Ganho':
                it["ganhos"] += 1
        for it in por_origem.values():
            it["taxa"] = round(it["ganhos"] / it["total"] * 100) if it["total"] else 0
        origens = sorted(por_origem.values(), key=lambda x: -x["total"])

        # --- por pessoa ---
        por_pessoa = {}
        for l in ativos:
            r = l.get('responsavel') or 'Sem responsável'
            it = por_pessoa.setdefault(r, {"pessoa": r, "leads": 0, "valor": 0.0, "ganhos": 0})
            it["leads"] += 1
            it["valor"] += valor(l)
        for l in ganhos:
            r = l.get('responsavel') or 'Sem responsável'
            it = por_pessoa.setdefault(r, {"pessoa": r, "leads": 0, "valor": 0.0, "ganhos": 0})
            it["ganhos"] += 1
        equipe = sorted(por_pessoa.values(), key=lambda x: -x["leads"])

        # --- ciclo de venda ---
        ciclos = []
        for l in ganhos:
            ini, fim = l.get('criado_em'), l.get('movido_em')
            if ini and fim:
                try:
                    d0 = datetime.fromisoformat(str(ini).replace('Z', '+00:00'))
                    d1 = datetime.fromisoformat(str(fim).replace('Z', '+00:00'))
                    ciclos.append(max(0, (d1 - d0).days))
                except Exception:
                    pass

        valor_ganho = sum(valor(l) for l in ganhos)
        saida = {
            "status": "sucesso",
            "periodo_dias": dias,
            "ver_valor": ver_valor,
            "kpis": {
                "ativos": len(ativos),
                "ganhos": len(ganhos),
                "perdidos": len(perdidos),
                "conversao": round(len(ganhos) / len(leads) * 100, 1) if leads else 0,
                "ciclo": round(_mediana(ciclos)),
            },
            "atencao": {
                "contato_hoje": len(contato_hoje),
                "parados": len(parados),
                "sem_contato": len(sem_contato),
            },
            "estoque": sorted(estoque.values(), key=lambda x: -x["qtd"]),
            "cascata": cascata,
            "destino": destino,
            "objecoes": sorted(({"objecao": k, "qtd": v} for k, v in objecoes.items()),
                               key=lambda x: -x["qtd"]),
            "perdas": sorted(({"motivo": k, "qtd": v} for k, v in perdas.items()),
                             key=lambda x: -x["qtd"]),
            "origens": origens,
            "equipe": equipe,
            "nutricao": len(nutricao),
        }
        # Valores só saem do servidor para quem pode vê-los.
        if ver_valor:
            saida["kpis"]["valor_funil"] = round(sum(valor(l) for l in ativos))
            saida["kpis"]["valor_ganho"] = round(valor_ganho)
            saida["kpis"]["valor_perdido"] = round(sum(valor(l) for l in perdidos))
            saida["kpis"]["ticket"] = round(valor_ganho / len(ganhos)) if ganhos else 0
            saida["valor_parado"] = round(sum(valor(l) for l in parados))
            saida["valor_nutricao"] = round(sum(valor(l) for l in nutricao))
        else:
            for it in saida["estoque"]:
                it.pop("valor", None)
            for it in saida["equipe"]:
                it.pop("valor", None)
        return jsonify(saida), 200
    except Exception as e:
        print("Erro em painel_comercial:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao montar o painel.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/catalogo', methods=['GET'])
def catalogo_capacidades():
    """O catálogo vive no código. A tela o consulta para saber o que
    existe, em vez de manter uma cópia própria que sairia de sincronia."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    itens = []
    for chave, (grupo, rotulo, desc, escopos, sensivel) in CATALOGO.items():
        itens.append({
            "chave": chave, "grupo": grupo, "rotulo": rotulo,
            "descricao": desc, "escopos": list(escopos), "sensivel": sensivel,
            # A tela usa isto para separar o que é base (todo mundo tem),
            # o que é opcional (decisão por pessoa) e o que é só do
            # Administrador.
            "so_admin": chave in CAPS_SO_ADMIN,
            "base": chave in CAPS_BASE,
            "opcional": chave in CAPS_OPCIONAIS,
            "alcance": chave in CAPS_ALCANCE,
        })
    return jsonify({
        "status": "sucesso",
        "capacidades": itens,
        "grupos": GRUPOS_ORDEM,
        "quadros": [{"chave": c, "nome": n} for c, n in QUADROS],
        "areas": [{"chave": c, "nome": n, "icone": i, "descricao": d}
                  for c, n, i, d in AREAS],
    }), 200


@app.route('/api/acessos/papeis', methods=['GET'])
def listar_papeis():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        papeis = (supabase.table("papeis").select("*").order("ordem").execute()).data or []
        caps = (supabase.table("papel_capacidades").select("*").execute()).data or []
        usuarios = (supabase.table("usuarios").select("id, papel_id").execute()).data or []

        por_papel = {}
        for c in caps:
            por_papel.setdefault(str(c["papel_id"]), {})[c["capacidade"]] = c["escopo"]
        contagem = {}
        for u in usuarios:
            if u.get("papel_id"):
                contagem[str(u["papel_id"])] = contagem.get(str(u["papel_id"]), 0) + 1

        for p in papeis:
            pid = str(p["id"])
            p["capacidades"] = por_papel.get(pid, {})
            # Quadros deixaram de ser do papel: cada pessoa tem os seus,
            # em usuarios.quadros. A chave fica vazia por compatibilidade.
            p["quadros"] = []
            p["pessoas"] = contagem.get(pid, 0)

        return jsonify({"status": "sucesso", "papeis": papeis}), 200
    except Exception as e:
        print("Erro em listar_papeis:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar papéis.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/papeis', methods=['POST'])
def criar_papel():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.get_json() or {}
        nome = (d.get("nome") or "").strip()
        if not nome:
            return jsonify({"status": "erro", "mensagem": "Informe o nome do papel."}), 400
        res = supabase.table("papeis").insert({
            "nome": nome,
            "descricao": (d.get("descricao") or "").strip() or None,
            "icone": d.get("icone") or "badge",
            "externo": bool(d.get("externo")),
            "ordem": int(d.get("ordem") or 99),
        }).execute()
        novo = (res.data or [None])[0]
        registrar("papel_criado", "papeis", novo and novo.get("id"), {"nome": nome})
        return jsonify({"status": "sucesso", "papel": novo}), 201
    except Exception as e:
        print("Erro em criar_papel:", e)
        msg = "Já existe um papel com esse nome." if "duplicate" in str(e).lower() else "Erro ao criar papel."
        return jsonify({"status": "erro", "mensagem": msg, "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/papeis/<papel_id>', methods=['PUT'])
def atualizar_papel(papel_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        atual = supabase.table("papeis").select("*").eq("id", papel_id).limit(1).execute()
        if not atual.data:
            return jsonify({"status": "erro", "mensagem": "Papel não encontrado."}), 404
        if atual.data[0].get("sistema"):
            return jsonify({"status": "erro",
                            "mensagem": "O papel de Administração não pode ser editado."}), 403

        d = request.get_json() or {}
        upd = {k: d[k] for k in ("nome", "descricao", "icone", "ordem") if k in d}
        if upd:
            supabase.table("papeis").update(upd).eq("id", papel_id).execute()

        # Capacidades: substitui o conjunto inteiro em vez de comparar
        # item a item. Com poucas dezenas, é mais simples e não deixa sobra.
        if "capacidades" in d:
            supabase.table("papel_capacidades").delete().eq("papel_id", papel_id).execute()
            linhas = []
            for cap, esc in (d["capacidades"] or {}).items():
                if cap not in CATALOGO:
                    continue          # ignora capacidade que não existe no código
                escopos = CATALOGO[cap][3]
                if escopos and esc not in escopos:
                    esc = escopos[-1]
                linhas.append({"papel_id": papel_id, "capacidade": cap,
                               "escopo": esc if escopos else "tudo"})
            if linhas:
                supabase.table("papel_capacidades").insert(linhas).execute()

        registrar("papel_alterado", "papeis", papel_id,
                  {"campos": list(upd.keys()),
                   "capacidades": len(d.get("capacidades") or {}) if "capacidades" in d else None})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em atualizar_papel:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/papeis/<papel_id>', methods=['DELETE'])
def excluir_papel(papel_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        atual = supabase.table("papeis").select("*").eq("id", papel_id).limit(1).execute()
        if not atual.data:
            return jsonify({"status": "erro", "mensagem": "Papel não encontrado."}), 404
        if atual.data[0].get("sistema"):
            return jsonify({"status": "erro",
                            "mensagem": "O papel de Administração não pode ser removido."}), 403

        # Papel com gente dentro não some: as pessoas ficariam sem acesso
        # nenhum e ninguém entenderia por quê.
        uso = supabase.table("usuarios").select("id").eq("papel_id", papel_id).execute()
        if uso.data:
            return jsonify({"status": "erro",
                            "mensagem": "Há %d pessoa(s) com este papel. Mova-as antes de excluir."
                                        % len(uso.data)}), 400

        supabase.table("papeis").delete().eq("id", papel_id).execute()
        registrar("papel_excluido", "papeis", papel_id, {"nome": atual.data[0].get("nome")})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em excluir_papel:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/pessoas', methods=['GET'])
def listar_pessoas_acessos():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        # Nunca selecionar '*' aqui: a tabela ainda tem a coluna `senha`
        # em texto puro, e ela não pode sair do servidor.
        res = (supabase.table("usuarios")
               .select("id, nome, email, cargo, telefone, papel_id, equipe, ativo, "
                       "nivel_acesso, tipo_usuario, quadros, areas, ajustes, "
                       "ultimo_acesso, criado_em, senha_hash")
               .order("nome").execute())
        pessoas = res.data or []
        # O hash não pode sair do servidor. Vira um booleano: a tela só
        # precisa saber se a pessoa já tem senha definida.
        for p in pessoas:
            p["tem_senha"] = bool(p.pop("senha_hash", None))
        equipes = sorted({p["equipe"] for p in pessoas if p.get("equipe")})
        return jsonify({"status": "sucesso", "pessoas": pessoas, "equipes": equipes}), 200
    except Exception as e:
        print("Erro em listar_pessoas_acessos:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar pessoas.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/pessoas', methods=['POST'])
def criar_pessoa_acessos():
    """Cadastra uma pessoa direto na tela de Acessos."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.json or {}
        nome = (d.get("nome") or "").strip()
        email = (d.get("email") or "").strip().lower()
        senha = d.get("senha") or ""
        if not nome or not email:
            return jsonify({"status": "erro", "mensagem": "Nome e e-mail são obrigatórios."}), 400
        if len(senha) < 8:
            return jsonify({"status": "erro",
                            "mensagem": "A senha precisa de pelo menos 8 caracteres."}), 400

        existe = supabase.table("usuarios").select("id").eq("email", email).limit(1).execute()
        if existe.data:
            return jsonify({"status": "erro",
                            "mensagem": "Já existe alguém com este e-mail."}), 409

        novo = {
            "nome": nome,
            "email": email,
            "cargo": (d.get("cargo") or "").strip() or None,
            "telefone": (d.get("telefone") or "").strip() or None,
            "equipe": (d.get("equipe") or "").strip() or None,
            "papel_id": d.get("papel_id") or None,
            "tipo_usuario": "interno",
            "nivel_acesso": d.get("nivel_acesso") or "colaborador",
            "ativo": True,
            # Só o hash. A coluna `senha` em texto puro é legado e não
            # recebe valor desde a correção do login.
            "senha_hash": gerar_hash(senha),
            "quadros": [q for q in (d.get("quadros") or []) if q in QUADRO_AREA],
            "areas": [a for a in (d.get("areas") or []) if a in AREAS_VALIDAS],
            "ajustes": {},
            "perm_modulos": [],
        }
        res = supabase.table("usuarios").insert(novo).execute()
        criado = (res.data or [{}])[0]
        registrar_auditoria('pessoa_criada', 'usuario', criado.get("id"),
                            {"nome": nome, "email": email})
        criado.pop("senha_hash", None)
        criado.pop("senha", None)
        return jsonify({"status": "sucesso", "pessoa": criado}), 201
    except Exception as e:
        print("Erro em criar_pessoa_acessos:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao cadastrar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/pessoas/<usuario_id>/alcance', methods=['PUT'])
def definir_alcance(usuario_id):
    """Define se a pessoa enxerga só o que é dela ou o quadro inteiro.

    Move as cinco capacidades de alcance de uma vez. Deixá-las como
    exceções separadas obrigaria a marcar cinco chips para dizer uma
    coisa só.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    alcance = (request.json or {}).get("alcance")
    if alcance not in ('proprio', 'quadro', 'padrao'):
        return jsonify({"status": "erro", "mensagem": "Alcance inválido."}), 400
    try:
        r = (supabase.table("usuarios").select("ajustes")
             .eq("id", usuario_id).limit(1).execute())
        ajs = dict((r.data or [{}])[0].get("ajustes") or {})
        agora = datetime.now(timezone.utc).isoformat()
        autor = session.get('usuario_nome')

        for cap in CAPS_ALCANCE:
            if alcance == 'padrao':
                # Volta ao que o nível define.
                ajs.pop(cap, None)
                continue
            permitidos = CATALOGO[cap][3]
            valor = alcance if alcance in permitidos else 'tudo'
            ajs[cap] = {"valor": valor, "por": autor, "em": agora}

        supabase.table("usuarios").update({"ajustes": ajs}).eq("id", usuario_id).execute()
        registrar_auditoria('alcance_alterado', 'usuario', usuario_id, {"alcance": alcance})
        return jsonify({"status": "sucesso", "ajustes": ajs}), 200
    except Exception as e:
        print("Erro em definir_alcance:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/pessoas/<usuario_id>/senha', methods=['PUT'])
def redefinir_senha_acessos(usuario_id):
    """Define uma senha nova para alguém.

    Quem redefine nunca vê a senha antiga — ela não existe em texto
    puro. A pessoa recebe a nova por fora e troca depois.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        senha = (request.json or {}).get("senha") or ""
        if len(senha) < 8:
            return jsonify({"status": "erro",
                            "mensagem": "A senha precisa de pelo menos 8 caracteres."}), 400
        supabase.table("usuarios").update({
            "senha_hash": gerar_hash(senha),
            "senha": None,          # apaga o legado em texto puro
        }).eq("id", usuario_id).execute()
        registrar_auditoria('senha_redefinida', 'usuario', usuario_id, {})
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em redefinir_senha_acessos:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao redefinir a senha.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/pessoas/<usuario_id>', methods=['PUT'])
def atualizar_acesso_pessoa(usuario_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not pode_gerir_acessos():
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        d = request.get_json() or {}
        upd = {}
        if "papel_id" in d:
            upd["papel_id"] = d["papel_id"] or None
        # Perder o quadro tira a pessoa da lista de executores dele:
        # senão ela continuaria recebendo card de um quadro que já não
        # consegue abrir.
        if "quadros" in d:
            novos = set(d.get("quadros") or [])
            try:
                atuais = (supabase.table("quadro_executores").select("quadro")
                          .eq("usuario_id", usuario_id).execute()).data or []
                for r in atuais:
                    if r.get("quadro") not in novos:
                        (supabase.table("quadro_executores").delete()
                         .eq("usuario_id", usuario_id).eq("quadro", r["quadro"]).execute())
            except Exception as e:
                print("Aviso: limpeza de executores:", e)

        for campo in ("cargo", "telefone"):
            if campo in d:
                upd[campo] = (d[campo] or "").strip() or None
        if "equipe" in d:
            upd["equipe"] = (d["equipe"] or "").strip() or None
        if "ativo" in d:
            upd["ativo"] = bool(d["ativo"])
        if "quadros" in d:
            upd["quadros"] = [q for q in (d["quadros"] or []) if q in QUADROS_VALIDOS]
        if "areas" in d:
            upd["areas"] = [a for a in (d["areas"] or []) if a in AREAS_VALIDAS]
        if "ajustes" in d:
            # Só aceita capacidade que existe no catálogo do código.
            # Exceção guarda quem deu e quando: "quem liberou valores
            # para a Barbara?" precisa ter resposta.
            # Capacidades de administração não viram exceção: se
            # virassem, o nível deixaria de significar alguma coisa.
            agora = datetime.now(timezone.utc).isoformat()
            autor = session.get('usuario_nome')
            antigos = {}
            try:
                r = (supabase.table("usuarios").select("ajustes")
                     .eq("id", usuario_id).limit(1).execute())
                if r.data:
                    antigos = r.data[0].get("ajustes") or {}
            except Exception as e:
                print("Aviso: ajustes anteriores:", e)

            limpos = {}
            for k, v in (d["ajustes"] or {}).items():
                if k not in CATALOGO or k in CAPS_SO_ADMIN:
                    continue
                antigo = antigos.get(k)
                # Só carimba autor e data quando o valor muda de fato.
                if isinstance(antigo, dict) and antigo.get("valor") == v:
                    limpos[k] = antigo
                else:
                    limpos[k] = {"valor": v, "por": autor, "em": agora}
            upd["ajustes"] = limpos
        if not upd:
            return jsonify({"status": "erro", "mensagem": "Nada a atualizar."}), 400

        # Trava: sempre precisa sobrar alguém com Administração ativo,
        # senão ninguém mais consegue entrar para consertar.
        if ("papel_id" in upd or upd.get("ativo") is False) and str(usuario_id):
            adm = supabase.table("papeis").select("id").eq("sistema", True).limit(1).execute()
            if adm.data:
                adm_id = str(adm.data[0]["id"])
                atual = (supabase.table("usuarios").select("papel_id, ativo")
                         .eq("id", usuario_id).limit(1).execute())
                era_adm = atual.data and str(atual.data[0].get("papel_id")) == adm_id
                sai = ("papel_id" in upd and str(upd["papel_id"]) != adm_id) or (upd.get("ativo") is False)
                if era_adm and sai:
                    todos = (supabase.table("usuarios").select("id, ativo")
                             .eq("papel_id", adm_id).execute()).data or []
                    restantes = [u for u in todos
                                 if str(u["id"]) != str(usuario_id) and u.get("ativo") is not False]
                    if not restantes:
                        return jsonify({"status": "erro",
                                        "mensagem": "Precisa sobrar ao menos uma pessoa ativa "
                                                    "com o papel de Administração."}), 400

        supabase.table("usuarios").update(upd).eq("id", usuario_id).execute()
        registrar("acesso_alterado", "usuarios", usuario_id, upd)
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em atualizar_acesso_pessoa:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/acessos/auditoria', methods=['GET'])
def listar_auditoria():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if not (pode('auditoria.ver') or session.get('nivel_acesso') == 'admin'):
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        q = supabase.table("auditoria").select("*")
        acao = request.args.get('acao')
        if acao:
            q = q.eq("acao", acao)
        res = q.order("criado_em", desc=True).limit(200).execute()
        return jsonify({"status": "sucesso", "registros": res.data or []}), 200
    except Exception as e:
        print("Erro em listar_auditoria:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar auditoria.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts', methods=['GET'])
def listar_posts():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        res = (supabase.table("posts").select("*")
               .is_("excluido_em", "null")
               .order("criado_em", desc=True).limit(120).execute())
        posts = res.data or []
        if not posts:
            return jsonify({"status": "sucesso", "posts": [], "reacoes": [],
                            "comentarios": [], "presencas": []}), 200

        ids = [p["id"] for p in posts]
        # Uma consulta por tabela em vez de uma por post: com 120 posts
        # seriam 360 idas ao banco.
        reacoes = (supabase.table("post_reacoes").select("*")
                   .in_("post_id", ids).execute()).data or []
        coments = (supabase.table("post_comentarios").select("*")
                   .in_("post_id", ids).is_("excluido_em", "null")
                   .order("criado_em").execute()).data or []
        presencas = (supabase.table("post_presencas").select("*")
                     .in_("post_id", ids).execute()).data or []

        return jsonify({"status": "sucesso", "posts": posts, "reacoes": reacoes,
                        "comentarios": coments, "presencas": presencas}), 200
    except Exception as e:
        print("Erro em listar_posts:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar o feed.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts', methods=['POST'])
def criar_post():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        d = request.get_json() or {}
        tipo = d.get("tipo", "post")
        if tipo not in TIPOS_POST:
            return jsonify({"status": "erro", "mensagem": "Tipo inválido."}), 400
        if not _pode_publicar(tipo):
            return jsonify({"status": "erro",
                            "mensagem": "Só admin e gestor publicam comunicados."}), 403
        corpo = (d.get("corpo") or "").strip()
        if not corpo:
            return jsonify({"status": "erro", "mensagem": "Escreva algo antes de publicar."}), 400
        if tipo == "evento" and not d.get("evento_data"):
            return jsonify({"status": "erro", "mensagem": "Evento precisa de data."}), 400

        fixar = bool(d.get("fixado")) and session.get('nivel_acesso') in ('admin', 'gestor')
        if fixar:
            # Um fixado por vez: dois destaques não destacam nada.
            supabase.table("posts").update({"fixado": False}).eq("fixado", True).execute()

        novo = {
            "tipo": tipo,
            "titulo": (d.get("titulo") or "").strip() or None,
            "corpo": corpo,
            "autor": session.get('usuario_nome', ''),
            "autor_id": str(session.get('usuario_id', '')),
            "fixado": fixar,
            "evento_data": d.get("evento_data") or None,
            "evento_local": (d.get("evento_local") or "").strip() or None,
            "anexos": d.get("anexos") or [],
        }
        res = supabase.table("posts").insert(novo).execute()
        return jsonify({"status": "sucesso", "post": (res.data or [None])[0]}), 201
    except Exception as e:
        print("Erro em criar_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao publicar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts/<post_id>', methods=['PUT'])
def atualizar_post(post_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        atual = supabase.table("posts").select("*").eq("id", post_id).limit(1).execute()
        if not atual.data:
            return jsonify({"status": "erro", "mensagem": "Post não encontrado."}), 404
        if not _pode_mexer_no_post(atual.data[0]):
            return jsonify({"status": "erro", "mensagem": "Você só edita os seus posts."}), 403

        d = request.get_json() or {}
        campos = ["titulo", "corpo", "evento_data", "evento_local", "anexos"]
        upd = {k: d[k] for k in campos if k in d}

        if "fixado" in d and session.get('nivel_acesso') in ('admin', 'gestor'):
            if d["fixado"]:
                supabase.table("posts").update({"fixado": False}).eq("fixado", True).execute()
            upd["fixado"] = bool(d["fixado"])

        if not upd:
            return jsonify({"status": "erro", "mensagem": "Nada a atualizar."}), 400
        upd["editado_em"] = datetime.now(timezone.utc).isoformat()
        supabase.table("posts").update(upd).eq("id", post_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em atualizar_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao salvar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts/<post_id>', methods=['DELETE'])
def excluir_post(post_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        atual = supabase.table("posts").select("*").eq("id", post_id).limit(1).execute()
        if not atual.data:
            return jsonify({"status": "erro", "mensagem": "Post não encontrado."}), 404
        if not _pode_mexer_no_post(atual.data[0]):
            return jsonify({"status": "erro", "mensagem": "Você só exclui os seus posts."}), 403
        supabase.table("posts").update(
            {"excluido_em": datetime.now(timezone.utc).isoformat(),
             "excluido_por": session.get('usuario_nome')}
        ).eq("id", post_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em excluir_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts/<post_id>/reacao', methods=['POST'])
def reagir_post(post_id):
    """Alterna a reação: se já existe, remove; se não, cria."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        emoji = (request.get_json() or {}).get("emoji") or "👍"
        usuario = session.get('usuario_nome', '')
        ja = (supabase.table("post_reacoes").select("id")
              .eq("post_id", post_id).eq("usuario", usuario)
              .eq("emoji", emoji).limit(1).execute())
        if ja.data:
            supabase.table("post_reacoes").delete().eq("id", ja.data[0]["id"]).execute()
            return jsonify({"status": "sucesso", "reagiu": False}), 200
        supabase.table("post_reacoes").insert(
            {"post_id": post_id, "usuario": usuario, "emoji": emoji}).execute()
        return jsonify({"status": "sucesso", "reagiu": True}), 200
    except Exception as e:
        print("Erro em reagir_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao reagir.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts/<post_id>/presenca', methods=['POST'])
def presenca_post(post_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        usuario = session.get('usuario_nome', '')
        ja = (supabase.table("post_presencas").select("id")
              .eq("post_id", post_id).eq("usuario", usuario).limit(1).execute())
        if ja.data:
            supabase.table("post_presencas").delete().eq("id", ja.data[0]["id"]).execute()
            return jsonify({"status": "sucesso", "confirmado": False}), 200
        supabase.table("post_presencas").insert(
            {"post_id": post_id, "usuario": usuario}).execute()
        return jsonify({"status": "sucesso", "confirmado": True}), 200
    except Exception as e:
        print("Erro em presenca_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao confirmar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts/<post_id>/comentarios', methods=['POST'])
def comentar_post(post_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        corpo = ((request.get_json() or {}).get("corpo") or "").strip()
        if not corpo:
            return jsonify({"status": "erro", "mensagem": "Escreva algo."}), 400
        novo = {
            "post_id": post_id,
            "autor": session.get('usuario_nome', ''),
            "corpo": corpo,
            "mencionados": (request.get_json() or {}).get("mencionados") or [],
        }
        res = supabase.table("post_comentarios").insert(novo).execute()
        return jsonify({"status": "sucesso", "comentario": (res.data or [None])[0]}), 201
    except Exception as e:
        print("Erro em comentar_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao comentar.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/posts/comentarios/<int:comentario_id>', methods=['DELETE'])
def excluir_comentario_post(comentario_id):
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        atual = (supabase.table("post_comentarios").select("*")
                 .eq("id", comentario_id).limit(1).execute())
        if not atual.data:
            return jsonify({"status": "erro", "mensagem": "Comentário não encontrado."}), 404
        c = atual.data[0]
        if (session.get('nivel_acesso') not in ('admin', 'gestor')
                and (c.get("autor") or '') != session.get('usuario_nome', '')):
            return jsonify({"status": "erro", "mensagem": "Você só exclui os seus."}), 403
        supabase.table("post_comentarios").update(
            {"excluido_em": datetime.now(timezone.utc).isoformat(),
             "excluido_por": session.get('usuario_nome')}
        ).eq("id", comentario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro em excluir_comentario_post:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/feed/upload', methods=['POST'])
def upload_anexo():
    """Sobe um arquivo para o Storage e devolve a URL pública.

    O arquivo passa pela função serverless, que no Vercel tem limite de
    ~4,5 MB por requisição. Acima disso o upload falha antes de chegar
    aqui — por isso a tela recusa arquivos grandes com aviso claro.
    """
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    if session.get('tipo_usuario') == 'externo':
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        arq = request.files.get('arquivo')
        if not arq or not arq.filename:
            return jsonify({"status": "erro", "mensagem": "Nenhum arquivo recebido."}), 400

        dados = arq.read()
        if len(dados) > 4 * 1024 * 1024:
            return jsonify({"status": "erro",
                            "mensagem": "Arquivo acima de 4 MB. Envie por link."}), 413

        # Nome único, preservando a extensão para o navegador saber abrir.
        base, ponto, ext = arq.filename.rpartition('.')
        ext = ('.' + ext.lower()) if ponto else ''
        caminho = "%s/%s%s" % (
            datetime.now(timezone.utc).strftime('%Y-%m'),
            secrets.token_urlsafe(16), ext)

        supabase.storage.from_(BUCKET_FEED).upload(
            caminho, dados,
            {"content-type": arq.mimetype or "application/octet-stream",
             "cache-control": "3600"})
        url = supabase.storage.from_(BUCKET_FEED).get_public_url(caminho)

        return jsonify({"status": "sucesso", "anexo": {
            "nome": arq.filename, "url": url,
            "tipo": arq.mimetype or "", "tamanho": len(dados)}}), 201
    except Exception as e:
        print("Erro em upload_anexo:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao enviar o arquivo.",
                        "detalhe": str(e)[:300]}), 500


@app.route('/api/timelogs', methods=['GET'])
def listar_timelogs():
    """Registros de tempo num intervalo de datas, com as permissões do usuário aplicadas.
    Usado pela Agenda para mostrar o que foi realizado, inclusive o tempo
    iniciado pelo quadro (que vem com planejamento_id nulo)."""
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    try:
        de = request.args.get('de')
        ate = request.args.get('ate')
        if not de or not ate:
            return jsonify({"status": "erro", "mensagem": "Informe de e ate."}), 400

        res = (supabase.table("time_logs").select("*")
               .gte("criado_em", de + "T00:00:00")
               .lte("criado_em", ate + "T23:59:59")
               .order("criado_em", desc=True).execute())
        logs = res.data or []
        if not logs:
            return jsonify({"status": "sucesso", "logs": []}), 200

        # Mesma regra de visibilidade dos projetos: ninguém vê tempo de
        # projeto que já não poderia ver na listagem.
        res_proj = supabase.table("projetos").select("*").execute()
        projetos = [p for p in (res_proj.data or []) if not p.get("excluido_em")]
        permitidos = {str(p.get("id")) for p in filtrar_projetos_permitidos(projetos)}
        logs = [l for l in logs if str(l.get("projeto_id")) in permitidos]

        return jsonify({"status": "sucesso", "logs": logs}), 200
    except Exception as e:
        print("Erro em /api/timelogs:", e)
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar registros."}), 500


@app.route('/api/planejamento', methods=['GET'])
def listar_planejamento():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        from datetime import date
        hoje_iso = date.today().isoformat()

        # Restrição de visibilidade (externo/personalizado)
        filtro_cliente = None
        if is_externo() or is_personalizado():
            filtro_cliente = set(projetos_visiveis_cliente())

        # Mapa de projeto -> contexto (nome, área, empresa)
        res_proj = supabase.table("projetos").select("id, nome_projeto, area, empresa").execute()
        mapa_proj = {str(p["id"]): p for p in res_proj.data}

        # ===== 1. Carrega os REALIZADOS (time_logs) =====
        # Indexado por (projeto, dia, colaborador, atividade) para cruzar com o planejado
        # exatamente pela mesma atividade. Também mantém um índice mais amplo
        # (projeto, dia, colaborador) só para somar tempo de realizados avulsos.
        realizados_idx = {}   # chave (projeto_id, dia, colab_lower, atividade_lower) -> {tempo...}
        realizados_lista = [] # todos os logs
        def _norm(s):
            return (s or "").strip().lower()
        try:
            page_size = 1000
            offset = 0
            while True:
                res_logs = supabase.table("time_logs").select("*").range(offset, offset + page_size - 1).execute()
                if not res_logs.data: break
                for log in res_logs.data:
                    if filtro_cliente is not None and str(log.get("projeto_id")) not in filtro_cliente:
                        continue
                    data_ref = log.get("data_inicio_atividade") or log.get("criado_em")
                    dia = str(data_ref)[:10] if data_ref else None
                    if not dia: continue
                    pid = str(log.get("projeto_id"))
                    colab = (log.get("colaborador") or "").strip()
                    tarefa = log.get("descricao_tarefa") or "Atividade registrada"
                    chave = (pid, dia, _norm(colab), _norm(tarefa))
                    if chave not in realizados_idx:
                        realizados_idx[chave] = {"tempo": 0, "colaborador": colab, "projeto_id": pid, "dia": dia, "tarefa": tarefa}
                    realizados_idx[chave]["tempo"] += (log.get("tempo_segundos") or 0)
                    realizados_lista.append({
                        "projeto_id": pid, "dia": dia, "colaborador": colab,
                        "tarefa": tarefa,
                        "tempo": log.get("tempo_segundos") or 0,
                        "criado_em": log.get("criado_em")
                    })
                if len(res_logs.data) < page_size: break
                offset += page_size
        except Exception as erro_logs:
            print(f"[AVISO] Falha ao carregar realizados: {str(erro_logs)}")

        # Marca quais chaves de realizado já foram "consumidas" por um planejamento
        chaves_consumidas = set()
        itens = []

        # ===== 2. PLANEJADOS: cada um vira UM item, com status cruzado pela MESMA atividade =====
        res = supabase.table("planejamento_diario").select("*").order("data_planejada", desc=False).order("criado_em", desc=False).execute()
        for p in res.data:
            pid = str(p.get("projeto_id"))
            if filtro_cliente is not None and pid not in filtro_cliente:
                continue
            dia = str(p.get("data_planejada"))[:10] if p.get("data_planejada") else None
            colab = (p.get("colaborador") or "").strip()
            atividade = p.get("atividade") or ""
            chave = (pid, dia, _norm(colab), _norm(atividade))

            # Houve execução dessa MESMA atividade nesse projeto+dia+colaborador?
            exec_info = realizados_idx.get(chave)
            if exec_info:
                status = "realizado"
                tempo = exec_info["tempo"]
                chaves_consumidas.add(chave)
            else:
                # Sem execução: se o dia já passou, é não-realizado (vermelho); senão, planejado (cinza)
                if dia and dia < hoje_iso:
                    status = "nao_realizado"
                else:
                    status = "planejado"
                tempo = None

            proj = mapa_proj.get(pid, {})
            itens.append({
                "id": p.get("id"),
                "status": status,
                "origem": "planejado",
                "projeto_id": p.get("projeto_id"),
                "colaborador": p.get("colaborador"),
                "atividade": p.get("atividade"),
                "data": dia,
                "criado_em": p.get("criado_em"),
                "tempo_segundos": tempo,
                "nome_projeto": proj.get("nome_projeto"),
                "area": proj.get("area"),
                "empresa": proj.get("empresa")
            })

        # ===== 3. REALIZADOS SEM PLANEJAMENTO: timer dado sem ter planejado aquela atividade =====
        # Um item por (projeto, dia, colaborador, atividade) que não casou com um planejado.
        vistos = set()
        for r in realizados_lista:
            chave = (r["projeto_id"], r["dia"], _norm(r["colaborador"]), _norm(r["tarefa"]))
            if chave in chaves_consumidas:
                continue  # já apareceu como planejado->realizado
            if chave in vistos:
                continue  # agrupa: um item por projeto+dia+colaborador+atividade
            vistos.add(chave)
            info = realizados_idx.get(chave, {})
            proj = mapa_proj.get(r["projeto_id"], {})
            itens.append({
                "id": "log_" + r["projeto_id"] + "_" + r["dia"] + "_" + str(abs(hash(_norm(r["tarefa"]))) % 100000),
                "status": "realizado",
                "origem": "realizado",
                "projeto_id": r["projeto_id"],
                "colaborador": r["colaborador"],
                "atividade": r["tarefa"],
                "data": r["dia"],
                "criado_em": r["criado_em"],
                "tempo_segundos": info.get("tempo", r["tempo"]),
                "nome_projeto": proj.get("nome_projeto"),
                "area": proj.get("area"),
                "empresa": proj.get("empresa")
            })

        return jsonify({"status": "sucesso", "planejamentos": itens}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no GET Planejamento: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar agenda."}), 500

@app.route('/api/planejamento', methods=['POST'])
def criar_planejamento():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if eh_visualizador(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        novo = {
            "projeto_id": dados.get("projeto_id"),
            "colaborador": dados.get("colaborador"),
            "atividade": dados.get("atividade"),
            "data_planejada": dados.get("data_planejada"),
            "status": "Planejado"
        }
        res = supabase.table("planejamento_diario").insert(novo).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        erro_msg = str(e)
        print(f"[CRITICAL] Erro no POST Planejamento: {erro_msg}")
        return jsonify({"status": "erro", "mensagem": erro_msg}), 500

@app.route('/api/planejamento/<item_id>', methods=['PUT'])
def atualizar_planejamento(item_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    try:
        atualizacao = {}
        if "projeto_id" in dados: atualizacao["projeto_id"] = dados["projeto_id"]
        if "atividade" in dados: atualizacao["atividade"] = dados["atividade"]
        if "data_planejada" in dados: atualizacao["data_planejada"] = dados["data_planejada"]
        if "colaborador" in dados: atualizacao["colaborador"] = dados["colaborador"]
        if "status" in dados: atualizacao["status"] = dados["status"]
        supabase.table("planejamento_diario").update(atualizacao).eq("id", item_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no PUT Planejamento: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao atualizar atividade."}), 500

@app.route('/api/planejamento/<item_id>', methods=['DELETE'])
def excluir_planejamento(item_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        supabase.table("planejamento_diario").delete().eq("id", item_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir atividade."}), 500


# ============================================================
# --- MÓDULO OKR ---
# ============================================================

def pode_ver_okr():
    """Admin/gestor sempre; colaborador e personalizado conforme módulo liberado.
    Externo precisa do módulo 'okr' liberado."""
    nivel = session.get('nivel_acesso')
    if nivel in ('admin', 'gestor'):
        return True
    return pode_acessar_modulo('okr')

def clientes_okr_permitidos():
    """Retorna a lista de clientes que o usuário logado pode ver no OKR,
    e se ele tem direito ao seletor.
    - Externo: travado no cliente vinculado (sem seletor)
    - Admin/Gestor: todos os clientes (com seletor)
    - Personalizado: conforme perm_clientes_modo (com seletor filtrado)
    Retorna (lista_clientes, mostra_seletor, cliente_travado_id)."""
    res_clientes = supabase.table("clientes").select("id, nome_empresa, excluido_em").execute()
    todos = sorted(
        [{"id": str(c["id"]), "nome": c.get("nome_empresa")} for c in res_clientes.data if not c.get("excluido_em")],
        key=lambda x: (x["nome"] or "").lower()
    )

    # EXTERNO: travado no cliente vinculado, sem seletor
    if is_externo():
        cid = str(session.get('cliente_vinculado_id') or '')
        meus = [c for c in todos if c["id"] == cid]
        return meus, False, (cid or None)

    nivel = session.get('nivel_acesso')
    # ADMIN / GESTOR / COMUM: todos os clientes, com seletor
    if nivel in ('admin', 'gestor', 'comum'):
        return todos, True, None

    # PERSONALIZADO: conforme a permissão de clientes
    modo = session.get('perm_clientes_modo') or 'todos'
    if modo == 'todos':
        return todos, True, None
    elif modo == 'selecionados':
        ids = set(str(x) for x in (session.get('perm_clientes_ids') or []))
        permitidos = [c for c in todos if c["id"] in ids]
        return permitidos, True, None
    elif modo == 'proprios':
        # Clientes dos projetos onde ele é responsável
        try:
            meu_nome = (session.get('usuario_nome') or '').strip().lower()
            res_proj = supabase.table("projetos").select("cliente_id, responsavel, excluido_em").execute()
            ids_proprios = set()
            for p in res_proj.data:
                if p.get("excluido_em"): continue
                if (p.get("responsavel") or "").strip().lower() == meu_nome and p.get("cliente_id"):
                    ids_proprios.add(str(p["cliente_id"]))
            permitidos = [c for c in todos if c["id"] in ids_proprios]
            return permitidos, True, None
        except Exception:
            return [], True, None
    return todos, True, None

@app.route('/okr')
def okr_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login', proximo=request.path))
    if not pode_ver_okr():
        return redirect(url_for('index'))
    return render_template('okr.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))


@app.route('/api/okr/arvore', methods=['GET'])
def okr_arvore():
    """Retorna a árvore completa de OKR de um cliente: macro, departamentos,
    e dentro de cada departamento os objetivos -> KRs -> tarefas."""
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    cliente_id = request.args.get('cliente_id')
    try:
        # Clientes que ESTE usuário pode ver + se tem seletor
        clientes, mostra_seletor, cliente_travado = clientes_okr_permitidos()

        # Externo (ou travado): força o cliente vinculado, ignora o que veio na URL
        if cliente_travado:
            cliente_id = cliente_travado

        # Se não veio cliente e há um só permitido, já abre nele
        if not cliente_id and len(clientes) == 1:
            cliente_id = clientes[0]["id"]

        # Segurança: o cliente pedido tem que estar entre os permitidos
        ids_permitidos = {c["id"] for c in clientes}
        if cliente_id and cliente_id not in ids_permitidos:
            return jsonify({"erro": "Acesso negado a este cliente"}), 403

        if not cliente_id:
            return jsonify({"status": "sucesso", "clientes": clientes, "mostra_seletor": mostra_seletor, "macro": None, "departamentos": []}), 200

        # Macro objetivo do cliente
        res_macro = supabase.table("okr_macro_objetivos").select("*").eq("cliente_id", cliente_id).execute()
        macro = res_macro.data[0] if res_macro.data else None

        # Departamentos do cliente
        res_dept = supabase.table("okr_departamentos").select("*").eq("cliente_id", cliente_id).order("nome").execute()
        departamentos = res_dept.data or []

        # Para cada departamento, carrega objetivos -> KRs -> tarefas
        dept_ids = [d["id"] for d in departamentos]
        objetivos_por_dept = {d["id"]: [] for d in departamentos}

        if dept_ids:
            res_obj = supabase.table("okr_objetivos").select("*").in_("departamento_id", dept_ids).order("criado_em").execute()
            objetivos = res_obj.data or []
            obj_ids = [o["id"] for o in objetivos]

            krs_por_obj = {o["id"]: [] for o in objetivos}
            if obj_ids:
                res_kr = supabase.table("okr_key_results").select("*").in_("objetivo_id", obj_ids).order("criado_em").execute()
                krs = res_kr.data or []
                kr_ids = [k["id"] for k in krs]

                tarefas_por_kr = {k["id"]: [] for k in krs}
                if kr_ids:
                    res_task = supabase.table("okr_tarefas").select("*").in_("kr_id", kr_ids).order("criado_em").execute()
                    for t in (res_task.data or []):
                        tarefas_por_kr.setdefault(t["kr_id"], []).append(t)

                for k in krs:
                    k["tarefas"] = tarefas_por_kr.get(k["id"], [])
                    krs_por_obj.setdefault(k["objetivo_id"], []).append(k)

            for o in objetivos:
                o["key_results"] = krs_por_obj.get(o["id"], [])
                objetivos_por_dept.setdefault(o["departamento_id"], []).append(o)

        for d in departamentos:
            d["objetivos"] = objetivos_por_dept.get(d["id"], [])

        return jsonify({
            "status": "sucesso",
            "clientes": clientes,
            "mostra_seletor": mostra_seletor,
            "cliente_atual": cliente_id,
            "macro": macro,
            "departamentos": departamentos
        }), 200
    except Exception as e:
        print(f"[CRITICAL] Erro na árvore OKR: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# --- MACRO OBJETIVO ---
@app.route('/api/okr/macro', methods=['POST'])
def okr_salvar_macro():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        macro_id = dados.get("id")
        cliente_id = dados.get("cliente_id")
        payload = {"titulo": dados.get("titulo"), "ciclo": dados.get("ciclo")}
        if macro_id:
            supabase.table("okr_macro_objetivos").update(payload).eq("id", macro_id).execute()
        else:
            # Um macro por cliente
            existe = supabase.table("okr_macro_objetivos").select("id").eq("cliente_id", cliente_id).execute()
            if existe.data:
                supabase.table("okr_macro_objetivos").update(payload).eq("id", existe.data[0]["id"]).execute()
            else:
                payload["cliente_id"] = cliente_id
                supabase.table("okr_macro_objetivos").insert(payload).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# --- DEPARTAMENTO ---
@app.route('/api/okr/departamento', methods=['POST'])
def okr_salvar_departamento():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        dept_id = dados.get("id")
        if dept_id:
            supabase.table("okr_departamentos").update({"nome": dados.get("nome")}).eq("id", dept_id).execute()
        else:
            supabase.table("okr_departamentos").insert({"nome": dados.get("nome"), "cliente_id": dados.get("cliente_id")}).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/okr/departamento/<dept_id>', methods=['DELETE'])
def okr_excluir_departamento(dept_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        supabase.table("okr_departamentos").delete().eq("id", dept_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# --- OBJETIVO / KR / TAREFA (criar) ---
@app.route('/api/okr/item', methods=['POST'])
def okr_criar_item():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    tipo = dados.get("tipo")
    try:
        if tipo == "objetivo":
            # Garante que existe um macro para vincular
            macro = supabase.table("okr_macro_objetivos").select("id").eq("cliente_id", dados.get("cliente_id")).limit(1).execute()
            macro_id = macro.data[0]["id"] if macro.data else None
            supabase.table("okr_objetivos").insert({
                "titulo": dados.get("titulo"),
                "departamento_id": dados.get("departamento_id"),
                "macro_objetivo_id": macro_id
            }).execute()
        elif tipo == "kr":
            supabase.table("okr_key_results").insert({
                "descricao": dados.get("descricao"),
                "objetivo_id": dados.get("parent_id"),
                "valor_meta": float(dados.get("valor_meta") or 0),
                "valor_atual": float(dados.get("valor_atual") or 0)
            }).execute()
        elif tipo == "tarefa":
            supabase.table("okr_tarefas").insert({
                "descricao": dados.get("descricao"),
                "kr_id": dados.get("parent_id"),
                "responsavel": dados.get("responsavel"),
                "prazo": dados.get("prazo") or None,
                "link_entregavel": dados.get("link_entregavel"),
                "status": "Não iniciado"
            }).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# --- OBJETIVO / KR / TAREFA (editar) ---
@app.route('/api/okr/item', methods=['PUT'])
def okr_editar_item():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    tipo = dados.get("tipo")
    item_id = dados.get("id")
    try:
        if tipo == "objetivo":
            supabase.table("okr_objetivos").update({"titulo": dados.get("titulo")}).eq("id", item_id).execute()
        elif tipo == "kr":
            supabase.table("okr_key_results").update({
                "descricao": dados.get("descricao"),
                "valor_atual": float(dados.get("valor_atual") or 0),
                "valor_meta": float(dados.get("valor_meta") or 0)
            }).eq("id", item_id).execute()
        elif tipo == "tarefa":
            supabase.table("okr_tarefas").update({
                "descricao": dados.get("descricao"),
                "responsavel": dados.get("responsavel"),
                "prazo": dados.get("prazo") or None,
                "link_entregavel": dados.get("link_entregavel"),
                "status": dados.get("status")
            }).eq("id", item_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

# --- OBJETIVO / KR / TAREFA (excluir) ---
@app.route('/api/okr/item', methods=['DELETE'])
def okr_excluir_item():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not pode_ver_okr(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    tipo = dados.get("tipo")
    item_id = dados.get("id")
    try:
        tabela = {"objetivo": "okr_objetivos", "kr": "okr_key_results", "tarefa": "okr_tarefas"}.get(tipo)
        if tabela:
            supabase.table(tabela).delete().eq("id", item_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# ============================================================
# --- MÓDULO PESQUISA DE CLIMA ---
# ============================================================
import secrets





# ===== MODELO BASE =====





# ===== PESQUISAS =====








# ===== DIMENSÕES / PERGUNTAS DA PESQUISA (editáveis) =====




# ===== LÍDERES E SETORES =====




# ===== RESPOSTA PÚBLICA (anônima, sem login) =====




# ============================================================
# --- MÓDULO GESTÃO DE DESEMPENHO ---
# ============================================================




# ===== CARGOS =====



# ===== COMPETÊNCIAS =====


# ===== PESSOAS =====



# ===== CICLOS =====





# adicionar participante (copia competências do cargo + cria avaliações conforme formato)



# ===== AVALIAÇÃO PÚBLICA (por token) =====



# ===== PDI =====


# ===== RESULTADOS (dashboard) =====


# --- API RESUMO DO HUB ---
@app.route('/api/hub/resumo', methods=['GET'])
def hub_resumo():
    if 'usuario_id' not in session:
        return jsonify({"erro": "Nao logado"}), 401
    resumo = {"clientes": None, "projetos": None}
    # Clientes
    try:
        if pode_acessar_modulo('clientes'):
            rc = supabase.table("clientes").select("id", count="exact").execute()
            resumo["clientes"] = rc.count or 0
    except Exception as e:
        print(f"[HUB] clientes: {str(e)}")
    # Projetos (não excluídos, respeitando permissões)
    try:
        res = supabase.table("projetos").select("*").execute()
        projs = [p for p in (res.data or []) if not p.get("excluido_em")]
        projs = filtrar_projetos_permitidos(projs)
        resumo["projetos"] = len(projs)
    except Exception as e:
        print(f"[HUB] projetos: {str(e)}")
    return jsonify({"status": "sucesso", "resumo": resumo}), 200


# ============================================================
# ACESSOS v2 -- ligacao com o modulo
#
# As dependencias sao injetadas em vez de importadas: `acessos_v2`
# nao conhece o `app.py`, o que evita import circular e deixa o
# modulo testavel isoladamente.
#
# Precisa ficar aqui, no fim: ARVORE_QUADROS, AREAS, CATALOGO e
# gerar_hash so existem depois de todo o arquivo ser lido.
# ============================================================
acessos_v2.configurar(
    supabase=supabase,
    catalogo=CATALOGO,
    arvore_quadros=ARVORE_QUADROS,
    areas=AREAS,
    gerar_hash=gerar_hash,
    registrar_auditoria=registrar_auditoria,
)
app.register_blueprint(acessos_v2.acessos_bp)

if __name__ == '__main__':
    app.run(debug=True, port=5000)
