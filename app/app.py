from flask import Flask, jsonify
import os
import socket

app = Flask(__name__)

@app.route("/health")
def health():
    return jsonify(status="healthy"), 200

@app.route("/")
def index():
    return jsonify(
        message="LexisNexis interview reference project",
        hostname=socket.gethostname(),
        bucket=os.environ.get("APP_BUCKET_NAME", "not-configured"),
    )

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3000)
# CI/CD pipeline test: verifying Prod blue/green + approval gate
# Fix: deploy-prod needs build-and-push output directly
