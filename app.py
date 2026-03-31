from flask import Flask, render_template, request, jsonify, redirect, session, url_for
from supabase import create_client, Client

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

# --- API ---

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
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

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
            "anotacoes": ""
        }
        supabase.table("projetos").insert(novo_projeto).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

@app.route('/api/projetos/<projeto_id>', methods=['PUT'])
def atualizar_projeto(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    dados = request.json
    try:
        atualizacao = {}
        if "status" in dados:
            atualizacao["status"] = dados.get("status")
        if "area" in dados: atualizacao["area"] = dados.get("area")
        if "responsavel" in dados: atualizacao["responsavel"] = dados.get("responsavel")
        supabase.table("projetos").update(atualizacao).eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

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
        # BLINDAGEM DUPLA: Se o banco recusar as datas, salva apenas os segundos!
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
            return jsonify({"status": "erro", "mensagem": str(erro_critico)}), 400

@app.route('/api/projetos/<projeto_id>/historico', methods=['GET'])
def historico_tempo(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        resposta = supabase.table("time_logs").select("*").eq("projeto_id", projeto_id).order("criado_em", desc=True).execute()
        return jsonify({"status": "sucesso", "historico": resposta.data}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

@app.route('/api/projetos/<projeto_id>', methods=['DELETE'])
def excluir_projeto(projeto_id):
    if 'usuario_id' not in session: return jsonify({"erro": "Nao logado"}), 401
    try:
        supabase.table("projetos").delete().eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)
