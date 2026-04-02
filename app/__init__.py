from flask import Flask
from .models import db
from flask_jwt_extended import JWTManager
from flask_cors import CORS

def create_app():
    app = Flask(__name__)
    
    CORS(app)
    # Configurações do banco e do JWT
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///nexus.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['JWT_SECRET_KEY'] = 'super-secret-key-mudar-em-prod'
    
    db.init_app(app)
    jwt = JWTManager(app)
    
    # Registrando as rotas UMA ÚNICA VEZ cada uma
    from .routes.auth import auth_bp
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    
    from .routes.ponto import ponto_bp
    app.register_blueprint(ponto_bp, url_prefix='/api/ponto')

    from .routes.gestor import gestor_bp
    app.register_blueprint(gestor_bp, url_prefix='/api/gestor')

    @app.route('/')
    def index():
        return {"mensagem": "API do Nexus rodando com sucesso!"}, 200

    @app.route('/favicon.ico')
    def favicon():
        return "", 204

    with app.app_context():
        db.create_all()
        
    return app