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
    return render_template('index.html', usuario=session.get('usuario_nome'))

@app.route('/board/<nome_quadro>')
def tela_projetos(nome_quadro):
    if 'usuario_id' not in session:
        return redirect(url_for('login'))
    return render_template('projetos.html', quadro_atual=nome_quadro)

# --- API PROJETOS ---

@app.route('/api/projetos', methods=['GET'])
def listar_projetos():
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res_projetos = supabase.table("projetos").select("*").execute()
        projetos = res_projetos.data
        res_tempo = supabase.table("time_logs").select("projeto_id, tempo_segundos").execute()
        tempos_agrupados = {}
        for log in res_tempo.data:
            pid = log['projeto_id']
            tempos_agrupados[pid] = tempos_agrupados.get(pid, 0) + log['tempo_segundos']
        for p in projetos:
            p['tempo_total_segundos'] = tempos_agrupados.get(p['id'], 0)
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
        
        # 1. Busca o status atual no banco ANTES de atualizar
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

            # 2. A MÁGICA PROTEGIDA: Tenta gravar no histórico, se der erro de banco, não trava o card
            if novo_status and novo_status != status_anterior:
                try:
                    supabase.table("historico_colunas").insert({
                        "projeto_id": projeto_id,
                        "status_anterior": status_anterior,
                        "status_novo": novo_status,
                        "movimentado_por": session.get("usuario_nome", "Sistema")
                    }).execute()
                except Exception as erro_hist:
                    print(f"[AVISO BI] Erro ao gravar histórico (não afeta o Kanban): {str(erro_hist)}")

        if "area" in dados: atualizacao["area"] = dados.get("area")
        if "responsavel" in dados: atualizacao["responsavel"] = dados.get("responsavel")
        if "empresa" in dados: atualizacao["empresa"] = dados.get("empresa")
        if "nome_projeto" in dados: atualizacao["nome_projeto"] = dados.get("nome_projeto")
        if "prazo_data" in dados: atualizacao["prazo_data"] = dados.get("prazo_data") if dados.get("prazo_data") else None
        if "is_scrum" in dados: atualizacao["is_scrum"] = bool(dados.get("is_scrum"))
        
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
        print(f"[CRITICAL] Erro no DELETE: {str(e)}")
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
            print("Erro Crítico no Timer:", erro_critico)
            return jsonify({"status": "erro", "mensagem": "Erro ao salvar log de tempo"}), 500

@app.route('/api/projetos/<projeto_id>/historico', methods=['GET'])
def historico_tempo(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        resposta = supabase.table("time_logs").select("*").eq("projeto_id", projeto_id).order("criado_em", desc=True).execute()
        return jsonify({"status": "sucesso", "historico": resposta.data}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no Histórico: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar histórico."}), 500

# --- API COMENTÁRIOS (HIERARQUIA E EDIÇÃO) ---

@app.route('/api/projetos/<projeto_id>/comentarios', methods=['GET'])
def listar_comentarios(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        res = supabase.table("comentarios").select("*").eq("projeto_id", projeto_id).order("criado_em", desc=False).execute()
        return jsonify({"status": "sucesso", "comentarios": res.data}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro ao listar comentários: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao carregar comentários."}), 500

@app.route('/api/projetos/<projeto_id>/comentarios', methods=['POST'])
def adicionar_comentario(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    texto = dados.get("texto")
    parent_id = dados.get("parent_id", None) # Recebe o ID do pai se for resposta
    
    if not texto: return jsonify({"erro": "Texto vazio"}), 400
    try:
        novo_comentario = {
            "projeto_id": projeto_id,
            "autor": session.get("usuario_nome", "Usuário"),
            "texto": texto,
            "parent_id": parent_id
        }
        supabase.table("comentarios").insert(novo_comentario).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print(f"[CRITICAL] Erro no POST Comentários: {str(e)}")
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
        print(f"[CRITICAL] Erro no PUT Comentário: {str(e)}")
        return jsonify({"status": "erro", "mensagem": "Erro ao editar comentário."}), 500

if __name__ == '__main__':
    app.run(debug=True, port=5000)
