from dotenv import load_dotenv
from app import create_app

# Carrega variáveis de ambiente do arquivo .env
load_dotenv()

app = create_app()

if __name__ == '__main__':
    # threaded=True é obrigatório para SSE funcionar (cada cliente fica em uma thread)
    app.run(debug=True, host='127.0.0.1', port=5000, threaded=True)