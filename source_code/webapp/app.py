import os
from flask import Flask, render_template, request, jsonify
import requests

app = Flask(__name__)

# In Docker: SCANNER_API=http://backend:8000/zombie-scan (set in docker-compose.yml)
# Locally:   falls back to 127.0.0.1 for direct python app.py usage
SCANNER_API = os.environ.get("SCANNER_API", "http://127.0.0.1:8000/zombie-scan")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/analyze", methods=["POST"])
def analyze():
    repo = request.json.get("repo")

    try:
        resp = requests.post(
            SCANNER_API,
            json={"repo_url": repo},
            timeout=int(os.environ.get("SCANNER_TIMEOUT", 600))
        )

        data = resp.json()

        # FastAPI validation errors return detail as a list of objects.
        # Flatten it into a readable string so the frontend never sees [object Object].
        if not resp.ok and isinstance(data.get("detail"), list):
            msgs = [e.get("msg", str(e)) for e in data["detail"]]
            # Strip FastAPI's "Value error, " prefix for cleaner display
            clean = "; ".join(m.replace("Value error, ", "") for m in msgs)
            data = {"detail": clean}

        return jsonify(data), resp.status_code

    except Exception:
        return jsonify({"error": "Scanner API unreachable"}), 500