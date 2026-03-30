from flask import Flask, render_template, request, jsonify, redirect
from supabase import create_client, Client
from datetime import datetime, timezone

app = Flask(__name__)

URL = "https://udqeheyyhvqlwejdwkbj.supabase.co"
KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InVkcWVoZXl5aHZxbHdlamR3a2JqIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzM0MTk3NTksImV4cCI6MjA4ODk5NTc1OX0.qo9kF_dcrVLycg0XV9dnFyIH2euHAC8FISbkgv3KNrQ"
supabase: Client = create_client(URL, KEY)

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/board/<nome_quadro>')
def tela_projetos(nome_quadro):
    return render_template('projetos.html', quadro_atual=nome_quadro)

@app.route('/api/projetos', methods=['GET'])
def listar_projetos():
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
    dados = request.json
    try:
        atualizacao = {}
        if "status" in dados:
            novo_status = dados.get("status")
            atualizacao["status"] = novo_status
            
            try:
                agora = datetime.now(timezone.utc).isoformat()
                atualizacao["data_status_atual"] = agora
                
                proj_atual = supabase.table("projetos").select("data_inicio").eq("id", projeto_id).execute()
                if proj_atual.data:
                    banco_inicio = proj_atual.data[0].get("data_inicio")
                    if novo_status not in ["Backlog", "Não Iniciado"] and not banco_inicio:
                        atualizacao["data_inicio"] = agora
                    
                    if novo_status in ["Finalizado", "Pausado"]:
                        atualizacao["data_conclusao"] = agora
                    else:
                        atualizacao["data_conclusao"] = None
            except Exception as err_data:
                print(f"Aviso - Ignorando datas no projeto: {err_data}")
                atualizacao.pop("data_status_atual", None)
                atualizacao.pop("data_inicio", None)
                atualizacao.pop("data_conclusao", None)

        if "area" in dados: atualizacao["area"] = dados.get("area")
        if "responsavel" in dados: atualizacao["responsavel"] = dados.get("responsavel")
        if "anotacoes" in dados: atualizacao["anotacoes"] = dados.get("anotacoes")
            
        supabase.table("projetos").update(atualizacao).eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

@app.route('/api/projetos/<projeto_id>/timer', methods=['POST'])
def salvar_tempo(projeto_id):
    dados = request.json
    try:
        novo_log = {
            "projeto_id": projeto_id,
            "colaborador": dados.get("colaborador", "Jhonattan Luiz"), 
            "descricao_tarefa": dados.get("descricao_tarefa", "Atividade Padrão"),
            "tempo_segundos": int(dados.get("tempo_segundos", 0))
        }
        
        # BLINDAGEM DE ERROS: Tenta salvar com as datas exatas. Se falhar, salva sem as datas.
        try:
            log_com_data = novo_log.copy()
            if dados.get("data_inicio_atividade"):
                log_com_data["data_inicio_atividade"] = dados.get("data_inicio_atividade")
            if dados.get("data_fim_atividade"):
                log_com_data["data_fim_atividade"] = dados.get("data_fim_atividade")
            supabase.table("time_logs").insert(log_com_data).execute()
        except Exception as e:
            print(f"Aviso - Banco sem as colunas de data no time_logs. Salvando apenas o tempo bruto. Erro: {e}")
            supabase.table("time_logs").insert(novo_log).execute()

        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        print("Erro crítico ao salvar timer:", e)
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

@app.route('/api/projetos/<projeto_id>/historico', methods=['GET'])
def historico_tempo(projeto_id):
    try:
        resposta = supabase.table("time_logs").select("*").eq("projeto_id", projeto_id).order("criado_em", desc=True).execute()
        return jsonify({"status": "sucesso", "historico": resposta.data}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

@app.route('/api/projetos/<projeto_id>', methods=['DELETE'])
def excluir_projeto(projeto_id):
    try:
        supabase.table("projetos").delete().eq("id", projeto_id).execute()
        return jsonify({"status": "sucesso"}), 200
    except Exception as e:
        return jsonify({"status": "erro", "mensagem": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True, port=5000)