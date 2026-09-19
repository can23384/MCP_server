"""
pharmacy_mcp_server.py

Local MCP server for the CC3067 Project 1 pharmacy-chain use case.

Important project constraint:
- This server does NOT use an MCP SDK.
- JSON-RPC 2.0 and the small MCP surface used by the chatbot are handled
  manually over stdio.

The catalog, inventory and orders are intentionally simulated for an academic
prototype. The recommendation tool only suggests a small set of OTC products
and escalates higher-risk situations instead of diagnosing or prescribing.
"""

from __future__ import annotations

import json
import sys
import uuid
from typing import Any

PROTOCOL_VERSION = "2025-11-25"


PRODUCTS: dict[str, dict[str, Any]] = {
    "MED-001": {
        "name": "Paracetamol 500 mg",
        "generic_name": "paracetamol",
        "category": "pain_fever",
        "otc": True,
        "price": 18.50,
        "stock": 40,
        "uses": ["dolor de cabeza", "dolor leve", "fiebre", "malestar general"],
        "warnings": [
            "No usar si existe alergia al paracetamol.",
            "Personas con enfermedad hepática deben consultar a un profesional.",
            "Seguir siempre las instrucciones de la etiqueta del producto.",
        ],
    },
    "MED-002": {
        "name": "Loratadina 10 mg",
        "generic_name": "loratadina",
        "category": "allergy",
        "otc": True,
        "price": 24.00,
        "stock": 25,
        "uses": ["estornudos por alergia", "secreción nasal por alergia", "picazón por alergia"],
        "warnings": [
            "No usar si existe alergia a la loratadina.",
            "Consultar antes de usar durante embarazo o lactancia.",
            "Seguir siempre las instrucciones de la etiqueta del producto.",
        ],
    },
    "MED-003": {
        "name": "Sales de rehidratación oral",
        "generic_name": "sales de rehidratación oral",
        "category": "hydration",
        "otc": True,
        "price": 12.00,
        "stock": 55,
        "uses": ["rehidratación", "pérdida de líquidos por diarrea", "pérdida de líquidos por vómitos"],
        "warnings": [
            "No sustituye una evaluación médica cuando existe deshidratación severa.",
            "Seguir las instrucciones de preparación indicadas en el empaque.",
        ],
    },
    "MED-004": {
        "name": "Antiácido de carbonato de calcio",
        "generic_name": "carbonato de calcio",
        "category": "heartburn",
        "otc": True,
        "price": 20.00,
        "stock": 30,
        "uses": ["acidez ocasional", "agruras ocasionales"],
        "warnings": [
            "Si la acidez es frecuente o intensa, consultar a un profesional.",
            "Seguir siempre las instrucciones de la etiqueta del producto.",
        ],
    },
}

ORDERS: dict[str, dict[str, Any]] = {}

RED_FLAG_TERMS = {
    "dolor de pecho",
    "dificultad para respirar",
    "no puedo respirar",
    "desmayo",
    "convulsion",
    "convulsión",
    "sangrado abundante",
    "vomito con sangre",
    "vómito con sangre",
    "reaccion alergica severa",
    "reacción alérgica severa",
    "hinchazon de garganta",
    "hinchazón de garganta",
}

SYMPTOM_RULES: list[tuple[set[str], list[str], str]] = [
    (
        {"dolor de cabeza", "fiebre", "dolor leve", "malestar", "dolor muscular"},
        ["MED-001"],
        "Síntomas leves de dolor o fiebre pueden ser compatibles con un analgésico/antitérmico OTC.",
    ),
    (
        {"alergia", "estornudos", "picazon", "picazón", "secrecion nasal", "secreción nasal"},
        ["MED-002"],
        "Síntomas compatibles con alergia leve pueden ser atendidos con un antihistamínico OTC.",
    ),
    (
        {"diarrea", "vomitos", "vómitos", "deshidratacion", "deshidratación"},
        ["MED-003"],
        "Cuando hay pérdida leve de líquidos, la prioridad es mantener la hidratación.",
    ),
    (
        {"acidez", "agruras", "ardor estomacal"},
        ["MED-004"],
        "La acidez ocasional puede ser compatible con un antiácido OTC.",
    ),
]


def _write_json(message: dict[str, Any]) -> None:
    """Writes exactly one JSON-RPC message to stdout."""
    sys.stdout.write(json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n")
    sys.stdout.flush()


def _debug(message: str) -> None:
    """Debug output must go to stderr so stdout stays valid JSON-RPC."""
    print(f"[pharmacy-mcp] {message}", file=sys.stderr, flush=True)


def _response(id_: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": id_, "result": result}


def _error(id_: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": id_, "error": error}


def _tool_result(data: Any, *, is_error: bool = False) -> dict[str, Any]:
    """MCP-style tool result containing text plus machine-readable content."""
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(data, ensure_ascii=False, indent=2),
            }
        ],
        "structuredContent": data,
        "isError": is_error,
    }


def _public_product(product_id: str, product: dict[str, Any]) -> dict[str, Any]:
    return {
        "product_id": product_id,
        "name": product["name"],
        "generic_name": product["generic_name"],
        "category": product["category"],
        "otc": product["otc"],
        "price_gtq": product["price"],
        "stock": product["stock"],
        "uses": product["uses"],
        "warnings": product["warnings"],
    }


def _normalize_terms(values: list[str]) -> list[str]:
    return [str(value).strip().lower() for value in values if str(value).strip()]


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "name": "list_products",
            "description": (
                "Lists simulated OTC products sold by the pharmacy. Use this to inspect the "
                "catalog before recommending or purchasing a product."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "category": {
                        "type": "string",
                        "description": "Optional category filter such as pain_fever, allergy, hydration or heartburn.",
                    }
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "recommend_otc",
            "description": (
                "For this academic pharmacy prototype, evaluates a short list of reported symptoms and may return "
                "a conservative OTC product suggestion. It does not diagnose or prescribe. If there are red flags, "
                "the patient is under 18, pregnant, or the situation is unsupported, it requests professional review."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "symptoms": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                        "description": "Symptoms reported by the customer, preferably in Spanish.",
                    },
                    "age": {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 120,
                        "description": "Customer age in years.",
                    },
                    "pregnant": {
                        "type": "boolean",
                        "description": "Whether the customer reports being pregnant.",
                    },
                    "allergies": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Known medication allergies reported by the customer.",
                    },
                    "conditions": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Relevant chronic conditions reported by the customer.",
                    },
                },
                "required": ["symptoms", "age"],
                "additionalProperties": False,
            },
        },
        {
            "name": "check_inventory",
            "description": "Checks current simulated inventory and price for one pharmacy product.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Product identifier, e.g. MED-001."}
                },
                "required": ["product_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "create_order",
            "description": (
                "Creates a simulated purchase order for an OTC product and decrements in-memory inventory. "
                "Only call this after the customer explicitly asks to buy the product."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "product_id": {"type": "string", "description": "Product identifier, e.g. MED-001."},
                    "quantity": {"type": "integer", "minimum": 1, "maximum": 10},
                    "customer_name": {
                        "type": "string",
                        "minLength": 1,
                        "description": "Name used for this simulated order.",
                    },
                },
                "required": ["product_id", "quantity", "customer_name"],
                "additionalProperties": False,
            },
        },
        {
            "name": "get_order",
            "description": "Retrieves a previously created simulated pharmacy order by its order id.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order identifier returned by create_order."}
                },
                "required": ["order_id"],
                "additionalProperties": False,
            },
        },
    ]


def list_products(arguments: dict[str, Any]) -> dict[str, Any]:
    category = str(arguments.get("category", "")).strip().lower()
    products = []
    for product_id, product in PRODUCTS.items():
        if category and product["category"] != category:
            continue
        products.append(_public_product(product_id, product))
    return {"products": products, "count": len(products)}


def recommend_otc(arguments: dict[str, Any]) -> dict[str, Any]:
    symptoms_raw = arguments.get("symptoms")
    age = arguments.get("age")
    pregnant = bool(arguments.get("pregnant", False))
    allergies = _normalize_terms(arguments.get("allergies") or [])
    conditions = _normalize_terms(arguments.get("conditions") or [])

    if not isinstance(symptoms_raw, list) or not symptoms_raw:
        return {"status": "invalid_input", "message": "Se requiere al menos un síntoma."}
    if not isinstance(age, int) or isinstance(age, bool):
        return {"status": "invalid_input", "message": "La edad debe ser un número entero."}

    symptoms = _normalize_terms(symptoms_raw)
    joined_symptoms = " | ".join(symptoms)

    matched_red_flags = sorted(term for term in RED_FLAG_TERMS if term in joined_symptoms)
    if matched_red_flags:
        return {
            "status": "refer",
            "requires_professional_review": True,
            "reason": "Se detectó al menos una señal de alarma.",
            "matched_red_flags": matched_red_flags,
            "recommendations": [],
            "message": "No se recomienda realizar una compra automática; se requiere evaluación profesional.",
        }

    if age < 18:
        return {
            "status": "refer",
            "requires_professional_review": True,
            "reason": "El prototipo no realiza recomendaciones automáticas para menores de edad.",
            "recommendations": [],
        }

    if pregnant:
        return {
            "status": "refer",
            "requires_professional_review": True,
            "reason": "El prototipo remite embarazo a revisión profesional antes de recomendar medicamentos.",
            "recommendations": [],
        }

    if conditions:
        # The demo intentionally does not attempt a complete drug-condition interaction engine.
        return {
            "status": "refer",
            "requires_professional_review": True,
            "reason": "Se reportaron condiciones médicas; el prototipo requiere revisión profesional.",
            "reported_conditions": conditions,
            "recommendations": [],
        }

    recommendations: list[dict[str, Any]] = []
    explanations: list[str] = []

    for keywords, product_ids, explanation in SYMPTOM_RULES:
        if any(keyword in joined_symptoms for keyword in keywords):
            explanations.append(explanation)
            for product_id in product_ids:
                product = PRODUCTS[product_id]
                allergy_text = " ".join(allergies)
                if product["generic_name"].lower() in allergy_text or product["name"].lower() in allergy_text:
                    continue
                if product["stock"] <= 0:
                    continue
                public = _public_product(product_id, product)
                if not any(existing["product_id"] == product_id for existing in recommendations):
                    recommendations.append(public)

    if not recommendations:
        return {
            "status": "refer",
            "requires_professional_review": True,
            "reason": "Los síntomas no coinciden con los escenarios OTC limitados de este prototipo o existe una restricción.",
            "recommendations": [],
        }

    return {
        "status": "otc_options",
        "requires_professional_review": False,
        "recommendations": recommendations,
        "reasoning": explanations,
        "safety_note": (
            "Resultado educativo de un catálogo simulado. No es diagnóstico ni receta. "
            "El usuario debe seguir la etiqueta y consultar a un profesional si los síntomas son intensos, persisten o empeoran."
        ),
    }


def check_inventory(arguments: dict[str, Any]) -> dict[str, Any]:
    product_id = str(arguments.get("product_id", "")).strip().upper()
    product = PRODUCTS.get(product_id)
    if product is None:
        return {"found": False, "product_id": product_id, "message": "Producto no encontrado."}
    return {
        "found": True,
        "product_id": product_id,
        "name": product["name"],
        "stock": product["stock"],
        "price_gtq": product["price"],
        "available": product["stock"] > 0,
    }


def create_order(arguments: dict[str, Any]) -> dict[str, Any]:
    product_id = str(arguments.get("product_id", "")).strip().upper()
    quantity = arguments.get("quantity")
    customer_name = str(arguments.get("customer_name", "")).strip()

    if not isinstance(quantity, int) or isinstance(quantity, bool) or not 1 <= quantity <= 10:
        return {"status": "rejected", "message": "La cantidad debe ser un entero entre 1 y 10."}
    if not customer_name:
        return {"status": "rejected", "message": "Se requiere customer_name."}

    product = PRODUCTS.get(product_id)
    if product is None:
        return {"status": "rejected", "message": "Producto no encontrado.", "product_id": product_id}
    if not product["otc"]:
        return {"status": "rejected", "message": "Este prototipo solo permite comprar productos OTC."}
    if product["stock"] < quantity:
        return {
            "status": "rejected",
            "message": "Inventario insuficiente.",
            "available_stock": product["stock"],
        }

    product["stock"] -= quantity
    order_id = f"ORD-{uuid.uuid4().hex[:8].upper()}"
    total = round(product["price"] * quantity, 2)
    order = {
        "order_id": order_id,
        "status": "created",
        "customer_name": customer_name,
        "product_id": product_id,
        "product_name": product["name"],
        "quantity": quantity,
        "unit_price_gtq": product["price"],
        "total_gtq": total,
        "remaining_stock": product["stock"],
        "payment_status": "not_charged_demo",
    }
    ORDERS[order_id] = order
    return order


def get_order(arguments: dict[str, Any]) -> dict[str, Any]:
    order_id = str(arguments.get("order_id", "")).strip().upper()
    order = ORDERS.get(order_id)
    if order is None:
        return {"found": False, "order_id": order_id, "message": "Orden no encontrada."}
    return {"found": True, "order": order}


TOOL_HANDLERS = {
    "list_products": list_products,
    "recommend_otc": recommend_otc,
    "check_inventory": check_inventory,
    "create_order": create_order,
    "get_order": get_order,
}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    if message.get("jsonrpc") != "2.0":
        return _error(message.get("id"), -32600, "Invalid Request", "jsonrpc must be 2.0")

    method = message.get("method")
    id_ = message.get("id")
    params = message.get("params") or {}

    # Notifications do not have an id and must not receive a response.
    if id_ is None:
        if method == "notifications/initialized":
            _debug("Client initialization completed.")
        return None

    if method == "initialize":
        return _response(
            id_,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "uvg-pharmacy-mcp", "version": "0.1.0"},
                "instructions": (
                    "Academic pharmacy-chain prototype. Tools expose a simulated OTC catalog, "
                    "conservative symptom routing, inventory and demo orders."
                ),
            },
        )

    if method == "ping":
        return _response(id_, {})

    if method == "tools/list":
        return _response(id_, {"tools": tool_definitions()})

    if method == "tools/call":
        if not isinstance(params, dict):
            return _error(id_, -32602, "Invalid params")
        name = params.get("name")
        arguments = params.get("arguments") or {}
        handler = TOOL_HANDLERS.get(name)
        if handler is None:
            return _response(id_, _tool_result({"error": f"Unknown tool: {name}"}, is_error=True))
        if not isinstance(arguments, dict):
            return _response(id_, _tool_result({"error": "Tool arguments must be an object."}, is_error=True))

        try:
            data = handler(arguments)
            return _response(id_, _tool_result(data))
        except Exception as exc:  # defensive: keep protocol alive during the demo
            _debug(f"Tool {name} failed: {exc}")
            return _response(id_, _tool_result({"error": str(exc)}, is_error=True))

    return _error(id_, -32601, "Method not found", method)


def main() -> None:
    _debug("Local Pharmacy MCP server started over stdio.")
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue

        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            _write_json(_error(None, -32700, "Parse error", str(exc)))
            continue

        if not isinstance(message, dict):
            _write_json(_error(None, -32600, "Invalid Request"))
            continue

        response = handle_request(message)
        if response is not None:
            _write_json(response)

    _debug("stdin closed; Pharmacy MCP server stopped.")


if __name__ == "__main__":
    main()
