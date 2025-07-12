# keep_alive.py

from flask import Flask
from threading import Thread

app = Flask("")

@app.route('/')
def home():
    return "I'm alive!"

def run():
    app.run(host="0.0.0.0", port=10000)

def keep_alive():
    # Run Flask server in a background thread
    t = Thread(target=run)
    t.daemon = True  # ensures thread exits when the main program does
    t.start()
