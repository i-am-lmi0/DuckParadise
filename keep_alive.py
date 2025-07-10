# keep_alive.py

from flask import Flask
import threading
import os

app = Flask(__name__)

@app.route("/")
def index():
    return "DuckParadise bot is alive!"

def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

def keep_alive():
    thread = threading.Thread(target=run)
    thread.start()
