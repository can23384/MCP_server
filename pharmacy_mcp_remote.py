import os

from flask import Flask, jsonify, request

from pharmacy_mcp_server import handle_request

app = Flask(__name__)


@app.get("/")
def home():
    return jsonify({
        "name": "UVG Pharmacy MCP Server",
        "status": "running",
        "transport": "HTTP",
        "protocol": "JSON-RPC 2.0"
    })


@app.get("/health")
def health():
    return jsonify({
        "status": "ok"
    })


@app.post("/mcp")
def mcp():
    try:
        message = request.get_json(force=True)
    except Exception:
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32700,
                "message": "Parse error"
            }
        }), 400

    if not isinstance(message, dict):
        return jsonify({
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": -32600,
                "message": "Invalid Request"
            }
        }), 400

    response = handle_request(message)

    # JSON-RPC notifications do not receive a response.
    if response is None:
        return "", 204

    return jsonify(response)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )