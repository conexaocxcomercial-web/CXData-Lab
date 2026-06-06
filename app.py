from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from supabase import create_client, Client
from datetime import datetime

app = Flask(__name__)
# CHAVE FIXA: Impede que a Vercel derrube o login a cada 5 minutos
app.secret_key = "cxdata_chave_mestra_oficial_2026_!@"

URL = "https://udqeheyyhvqlwejdwkbj.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVkcWVoZXl5aHZxbHdlamR3a2JqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM0MTk3NTksImV4cCI6MjA4ODk5NTc1OX0.qo9kF_dcrVLycg0XV9dnFyIH2euHAC8FISbkgv3KNrQ"
supabase: Client = create_client(URL, KEY)

# --- LOGIN E SEGURANÇA ---

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        dados = request.json
        email = dados.get('email')
        senha = dados.get('senha')

        res = supabase.table("usuarios").select("*").eq("email", email).eq("senha", senha).execute()

        if res.data:
            session['usuario_id'] = res.data[0]['id']
            session['usuario_nome'] = res.data[0]['nome']
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
    return render_template('index.html', usuario=session.get('usuario_nome'), usuario_nome=session.get('usuario_nome'))

@app.route('/board/<nome_quadro>')
def tela_projetos(nome_quadro):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('projetos.html', quadro_atual=nome_quadro, usuario_nome=session.get('usuario_nome'))

# --- API PROJETOS ---

@app.route('/api/projetos', methods=['GET'])
def listar_projetos():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res_projetos = supabase.table("projetos").select("*").execute()
        projetos = res_projetos.data
        
        # 1. Busca TODOS os tempos com paginação (Supabase limita 1000/query)
        tempos_agrupados = {}
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
    try:
        supabase.table("projetos").delete().eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": "Erro ao excluir o projeto."}), 500

# --- API TIMER ---

@app.route('/api/projetos/<projeto_id>/timer', methods=['POST'])
def salvar_tempo(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
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

# --- CLIENTES ---

@app.route('/clientes')
def clientes_page():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('clientes.html', usuario_nome=session.get('usuario_nome'))

@app.route('/api/clientes', methods=['GET'])
def listar_clientes():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res = supabase.table("clientes").select("*").order("nome_empresa", desc=False).execute()
        clientes = res.data

        # Conta projetos por cliente (para a listagem)
        res_proj = supabase.table("projetos").select("cliente_id, status, area, responsavel").execute()
        contagem = {}
        for p in res_proj.data:
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
        # Não deixa excluir se houver projetos vinculados
        res_proj = supabase.table("projetos").select("id").eq("cliente_id", cliente_id).execute()
        if res_proj.data and len(res_proj.data) > 0:
            return jsonify({"status": "erro", "mensagem": f"Cliente tem {len(res_proj.data)} projeto(s) vinculado(s). Não pode ser excluído."}), 400

        supabase.table("clientes").delete().eq("id", cliente_id).execute()
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

        # Projetos do cliente
        res_proj = supabase.table("projetos").select("*").eq("cliente_id", cliente_id).execute()
        projetos = res_proj.data

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


# --- PLANEJAMENTO DIÁRIO ---

@app.route('/planejamento')
def planejamento():
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('planejamento.html', usuario_nome=session.get('usuario_nome'))

@app.route('/api/planejamento', methods=['GET'])
def listar_planejamento():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res = supabase.table("planejamento_diario").select("*").order("data_planejada", desc=False).order("criado_em", desc=False).execute()
        return jsonify({"status": "sucesso", "planejamentos": res.data}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no GET Planejamento: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar planejamentos."}), 500

@app.route('/api/planejamento', methods=['POST'])
def criar_planejamento():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    try:
        novo = {
            "projeto_id": dados.get("projeto_id"),
            "colaborador": dados.get("colaborador"),
            "atividade": dados.get("atividade"),
            "data_planejada": dados.get("data_planejada"),
            "status": dados.get("status", "Planejado")
        }
        print(f"[DEBUG] Tentando inserir: {novo}")
        res = supabase.table("planejamento_diario").insert(novo).execute()
        print(f"[DEBUG] Resposta Supabase: {res}")
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


if __name__ == '__main__':
    app.run(debug=True, port=5000)
