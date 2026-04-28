from dotenv import load_dotenv
from app import create_app, socketio

load_dotenv()

app = create_app()

if __name__ == '__main__':
    # socketio.run() substitui app.run() — suporta WebSocket
    socketio.run(
        app,
        debug=True,
        host='127.0.0.1',
        port=5000,
        allow_unsafe_werkzeug=True,
    )
