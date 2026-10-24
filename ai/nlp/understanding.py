"""From a model's raw output to a checked command (shared by every parser and the app).

Every parser (rules, TF-IDF, Transformer) produces an intent with a confidence and entity spans.
`understand` turns that into what the operator sees and the backend can execute:

    {"text", "intent", "confidence", "entities": [{type, text, start, end, value}],
     "tool_calls", "requires_approval", "status", "question"}

`status` is
    "ok"                 a complete command (read-only ones may run at once, write ones need
                         approval)
    "needs_information"  the intent needs an entity that was not found (e.g. which robot?)
    "unsure"             the intent confidence is below the threshold: ask instead of guessing
    "out_of_scope"       not a warehouse command
"""

from __future__ import annotations

from ai.nlp.commands import normalize, requires_approval, tool_calls

MIN_CONFIDENCE = 0.5  # below this the copilot asks for confirmation instead of acting

QUESTION = {  # what to ask when an entity is missing
    "ROBOT": "Which robot do you mean (R1-R40)?",
    "ORDER": "Which order (e.g. O00125)?",
    "PRODUCT": "Which product or rack location?",
    "LOCATION": "Which product or rack location?",
    "AISLE": "Which aisle (1-52)?",
}


def understand(text: str, intent: str, confidence: float, spans: list[dict]) -> dict:
    entities = []
    for s in spans:
        value = normalize(s["type"], s["text"])
        if value is not None:
            entities.append({**s, "value": value})
    result = {
        "text": text,
        "intent": intent,
        "confidence": round(float(confidence), 3),
        "entities": entities,
        "tool_calls": [],
        "requires_approval": False,
        "status": "ok",
        "question": None,
    }
    if intent == "out_of_scope":
        result["status"] = "out_of_scope"
        result["question"] = "That is not something I can do in the warehouse."
        return result
    try:
        calls = tool_calls(intent, entities, text)
    except KeyError as missing:  # the intent needs an entity the message does not contain
        etype = missing.args[0]
        result["status"] = "needs_information"
        result["question"] = QUESTION.get(etype, f"Which {etype.lower()}?")
        return result
    result["tool_calls"] = calls
    result["requires_approval"] = requires_approval(calls)
    if confidence < MIN_CONFIDENCE:
        result["status"] = "unsure"
        result["question"] = f"Did you mean: {intent.replace('_', ' ')}?"
    return result
