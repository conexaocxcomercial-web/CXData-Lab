from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from supabase import create_client, Client
from datetime import datetime
import bcrypt
import secrets
import string
import os

app = Flask(__name__)
# CHAVE DE SESSÃO: lê de variável de ambiente, com fallback para não quebrar local
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "cxdata_chave_mestra_oficial_2026_!@")

# CREDENCIAIS SUPABASE: priorizam variáveis de ambiente (Vercel).
# O fallback mantém o sistema funcionando caso as env vars ainda não estejam configuradas.
URL = os.environ.get("SUPABASE_URL", "https://udqeheyyhvqlwejdwkbj.supabase.co")
KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVkcWVoZXl5aHZxbHdlamR3a2JqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM0MTk3NTksImV4cCI6MjA4ODk5NTc1OX0.qo9kF_dcrVLycg0XV9dnFyIH2euHAC8FISbkgv3KNrQ")
supabase: Client = create_client(URL, KEY)

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
        return True
    if nivel == 'colaborador':
        # Legado: colaborador acessa quadros e agenda
        return modulo in ('recrutamento', 'rhestrategico', 'geral', 'agenda')
    # comum, personalizado e externo: usam a lista explícita de módulos
    modulos = session.get('perm_modulos') or []
    return modulo in modulos

def filtrar_projetos_permitidos(projetos):
    """Recebe lista de projetos (dicts) e devolve só os que o usuário logado pode ver,
    combinando as dimensões de cliente e projeto. Não afeta admin/gestor."""
    nivel = session.get('nivel_acesso')

    # Admin e Gestor veem tudo (comportamento atual preservado)
    if nivel in ('admin', 'gestor'):
        return projetos

    # Comum: vê TODOS os dados (o controle é só de módulos, não de dados)
    if nivel == 'comum':
        return projetos

    # Colaborador (legado): só onde é responsável
    if nivel == 'colaborador':
        meu_nome = (session.get('usuario_nome') or '').strip().lower()
        return [p for p in projetos if (p.get('responsavel') or '').strip().lower() == meu_nome]

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

        # Busca o usuário só pelo e-mail
        res = supabase.table("usuarios").select("*").eq("email", email).execute()

        if not res.data:
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha inválidos"}), 401

        usuario = res.data[0]
        autenticado = False

        # 1. Se já tem hash, valida pelo hash
        if usuario.get("senha_hash"):
            autenticado = verificar_hash(senha, usuario["senha_hash"])
        # 2. Senão, valida pela senha em texto puro (legado) e CONVERTE para hash
        elif usuario.get("senha") is not None and senha == usuario["senha"]:
            autenticado = True
            try:
                novo_hash = gerar_hash(senha)
                supabase.table("usuarios").update({"senha_hash": novo_hash}).eq("id", usuario["id"]).execute()
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
            return jsonify({"status": "sucesso"}), 200
        else:
            return jsonify({"status": "erro", "mensagem": "E-mail ou senha inválidos"}), 401

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

# --- ROTAS PROTEGIDAS ---

@app.route('/')
def index():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    # Cliente vai direto para a Agenda (portal dele)
    if is_cliente():
        return redirect(url_for('planejamento'))
    return render_template('index.html', usuario=session.get('usuario_nome'), usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

@app.route('/board/<nome_quadro>')
def tela_projetos(nome_quadro):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    # Personalizado/externo: só acessa o quadro se tiver o módulo liberado
    if (is_personalizado() or is_externo()) and not pode_acessar_modulo(nome_quadro):
        return redirect(url_for('index'))
    return render_template('projetos.html', quadro_atual=nome_quadro, usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

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
        res_atual = supabase.table("projetos").select("status", "data_inicio").eq("id", projeto_id).execute()
        status_anterior = res_atual.data[0].get("status") if res_atual.data else None
        
        if "status" in dados:
            novo_status = dados.get("status")
            atualizacao["status"] = novo_status
            atualizacao["data_status_atual"] = datetime.utcnow().isoformat()

            status_pausa = ["Backlog", "Não Iniciado", "Pausado", "Finalizado", "Onboarding", "Cancelado"]
            if novo_status in status_pausa:
                atualizacao["data_conclusao"] = datetime.utcnow().isoformat()
            else:
                atualizacao["data_conclusao"] = None 
                
            if res_atual.data and not res_atual.data[0].get("data_inicio"):
                atualizacao["data_inicio"] = datetime.utcnow().isoformat()

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
        supabase.table("projetos").update({"excluido_em": datetime.now().isoformat()}).eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir o projeto."}), 500


# --- LIXEIRA (somente admin) ---

@app.route('/lixeira')
def lixeira_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    if not is_admin():
        return redirect(url_for('index'))
    return render_template('lixeira.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso'))

@app.route('/api/lixeira', methods=['GET'])
def listar_lixeira():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        res_proj = supabase.table("projetos").select("*").not_.is_("excluido_em", "null").execute()
        res_cli = supabase.table("clientes").select("*").not_.is_("excluido_em", "null").execute()
        return jsonify({"status": "sucesso", "projetos": res_proj.data or [], "clientes": res_cli.data or []}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro na lixeira: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar a lixeira."}), 500

@app.route('/api/lixeira/<tipo>/<item_id>/restaurar', methods=['PUT'])
def restaurar_item(tipo, item_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    tabela = "projetos" if tipo == "projeto" else "clientes" if tipo == "cliente" else None
    if not tabela: return jsonify({"status": "erro", "mensagem": "Tipo invalido."}), 400
    try:
        supabase.table(tabela).update({"excluido_em": None}).eq("id", item_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/lixeira/<tipo>/<item_id>/definitivo', methods=['DELETE'])
def excluir_definitivo(tipo, item_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    tabela = "projetos" if tipo == "projeto" else "clientes" if tipo == "cliente" else None
    if not tabela: return jsonify({"status": "erro", "mensagem": "Tipo invalido."}), 400
    try:
        supabase.table(tabela).delete().eq("id", item_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

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
            "data_fim_atividade": dados.get("data_fim_atividade")
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

@app.route('/configuracoes')
def configuracoes_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    if not is_admin():
        return redirect(url_for('index'))
    return render_template('configuracoes.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso'))

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
    Para níveis fixos (admin/gestor/colaborador) limpa as permissões granulares."""
    nivel = dados.get("nivel_acesso", "colaborador")
    tipo = dados.get("tipo_usuario", "interno")
    perms = {}

    # Personalizado (interno) OU qualquer externo: usa as permissões granulares
    if nivel == "personalizado" or tipo == "externo":
        perms["perm_modulos"] = dados.get("perm_modulos", [])
        perms["perm_clientes_modo"] = dados.get("perm_clientes_modo", "todos")
        perms["perm_clientes_ids"] = dados.get("perm_clientes_ids", [])
        perms["perm_projetos_modo"] = dados.get("perm_projetos_modo", "todos")
        perms["perm_projetos_ids"] = dados.get("perm_projetos_ids", [])
        perms["cliente_vinculado_id"] = dados.get("cliente_vinculado_id")
        if tipo == "externo":
            perms["papel_externo"] = dados.get("papel_externo", "visualizador")
    else:
        # Níveis fixos: zera as permissões granulares (limpeza)
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
            "senha": senha_texto,
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
            atualizacao["senha"] = dados["senha"]
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

@app.route('/externos')
def externos_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    if not is_admin():
        return redirect(url_for('index'))
    return render_template('externos.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso'))

@app.route('/api/externos', methods=['GET'])
def listar_externos():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        res = supabase.table("usuarios").select(
            "id, nome, email, cargo, nivel_acesso, tipo_usuario, papel_externo, cliente_vinculado_id, perm_modulos, perm_clientes_modo, perm_clientes_ids, perm_projetos_modo, perm_projetos_ids, criado_em"
        ).eq("tipo_usuario", "externo").order("nome", desc=False).execute()
        return jsonify({"status": "sucesso", "externos": res.data}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no GET Externos: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar usuários externos."}), 500

@app.route('/api/externos', methods=['POST'])
def criar_externo():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        senha_texto = dados.get("senha")
        if not senha_texto:
            return jsonify({"status": "erro", "mensagem": "Senha é obrigatória."}), 400
        if not dados.get("cliente_vinculado_id"):
            return jsonify({"status": "erro", "mensagem": "Selecione qual cliente é este usuário."}), 400

        novo = {
            "nome": dados.get("nome"),
            "email": dados.get("email"),
            "cargo": dados.get("cargo"),
            "nivel_acesso": "personalizado",   # externo usa a engine de permissões
            "tipo_usuario": "externo",
            "papel_externo": dados.get("papel_externo", "visualizador"),
            "senha": senha_texto,
            "senha_hash": gerar_hash(senha_texto)
        }
        novo.update(montar_permissoes({**dados, "tipo_usuario": "externo", "nivel_acesso": "personalizado"}))
        supabase.table("usuarios").insert(novo).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no POST Externo: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/externos/<usuario_id>', methods=['PUT'])
def atualizar_externo(usuario_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    dados = request.json
    try:
        atualizacao = {}
        if "nome" in dados: atualizacao["nome"] = dados["nome"]
        if "email" in dados: atualizacao["email"] = dados["email"]
        if "cargo" in dados: atualizacao["cargo"] = dados["cargo"]
        if "papel_externo" in dados: atualizacao["papel_externo"] = dados["papel_externo"]
        atualizacao["tipo_usuario"] = "externo"
        atualizacao["nivel_acesso"] = "personalizado"
        atualizacao.update(montar_permissoes({**dados, "tipo_usuario": "externo", "nivel_acesso": "personalizado"}))
        if dados.get("senha"):
            atualizacao["senha"] = dados["senha"]
            atualizacao["senha_hash"] = gerar_hash(dados["senha"])
        supabase.table("usuarios").update(atualizacao).eq("id", usuario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no PUT Externo: {str(e)}")
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

@app.route('/api/externos/<usuario_id>', methods=['DELETE'])
def excluir_externo(usuario_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    if not is_admin(): return jsonify({"erro": "Acesso negado"}), 403
    try:
        supabase.table("usuarios").delete().eq("id", usuario_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500


# --- CLIENTES ---

@app.route('/clientes')
def clientes_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
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
        supabase.table("clientes").update({"excluido_em": datetime.now().isoformat()}).eq("id", cliente_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 500

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
        return redirect(url_for('login'))
    pode = session.get('nivel_acesso') in ['admin', 'gestor'] or pode_acessar_modulo('dashboard')
    if not pode:
        return redirect(url_for('index'))
    return render_template('dashboard.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso'))

@app.route('/api/dashboard', methods=['GET'])
def dados_dashboard():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    pode = session.get('nivel_acesso') in ['admin', 'gestor'] or pode_acessar_modulo('dashboard')
    if not pode:
        return jsonify({"erro": "Acesso negado"}), 403
    try:
        # Filtros opcionais
        f_area = request.args.get('area')
        f_resp = request.args.get('responsavel')
        f_cliente = request.args.get('cliente_id')
        f_inicio = request.args.get('inicio')  # YYYY-MM-DD
        f_fim = request.args.get('fim')

        # Projetos ativos (fora da lixeira)
        res_proj = supabase.table("projetos").select("*").execute()
        projetos = [p for p in res_proj.data if not p.get("excluido_em")]

        # Aplica filtros de projeto
        if f_area: projetos = [p for p in projetos if p.get("area") == f_area]
        if f_resp: projetos = [p for p in projetos if p.get("responsavel") == f_resp]
        if f_cliente: projetos = [p for p in projetos if str(p.get("cliente_id")) == str(f_cliente)]

        ids_proj = set(str(p["id"]) for p in projetos)

        # Time logs (paginado) — para tempo, atividades, produtividade
        logs = []
        page_size = 1000
        offset = 0
        while True:
            res_t = supabase.table("time_logs").select("*").range(offset, offset + page_size - 1).execute()
            if not res_t.data: break
            logs.extend(res_t.data)
            if len(res_t.data) < page_size: break
            offset += page_size

        # Filtra logs pelos projetos visíveis e período
        def log_no_periodo(log):
            d = log.get("data_inicio_atividade") or log.get("criado_em")
            if not d: return True
            dia = str(d)[:10]
            if f_inicio and dia < f_inicio: return False
            if f_fim and dia > f_fim: return False
            return True

        logs = [l for l in logs if str(l.get("projeto_id")) in ids_proj and log_no_periodo(l)]

        # ===== KPIs GERAIS =====
        total_projetos = len(projetos)
        ativos = [p for p in projetos if p.get("status") not in ["Finalizado", "Cancelado"]]
        finalizados = [p for p in projetos if p.get("status") in ["Finalizado", "Cancelado"]]
        tempo_total = sum((l.get("tempo_segundos") or 0) for l in logs)

        # Projetos atrasados
        hoje = datetime.now().date().isoformat()
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
                dias_atraso = (datetime.now().date() - datetime.strptime(str(prazo)[:10], "%Y-%m-%d").date()).days
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
            dt_ini = dt_fim = datetime.now().date()

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

        return jsonify({
            "status": "sucesso",
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
        return redirect(url_for('login'))
    return render_template('planejamento.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

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
@app.route('/okr/gestao')
def okr_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    if not pode_ver_okr():
        return redirect(url_for('index'))
    return render_template('okr.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

@app.route('/okr/dashboard')
def okr_dashboard_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    if not pode_ver_okr():
        return redirect(url_for('index'))
    return render_template('okr_dashboard.html', usuario_nome=session.get('usuario_nome'), nivel_acesso=session.get('nivel_acesso', 'colaborador'))

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


if __name__ == '__main__':
    app.run(debug=True, port=5000)
