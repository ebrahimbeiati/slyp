"""
Scratch diagnostic - NOT part of the shipped test suite.

Every /analyse call makes a 400 to OpenAI and then a 200. This reproduces
both requests and prints exactly what the first one is rejected for.

NO DOCUMENT CONTENT LEAVES THIS SCRIPT OR APPEARS IN ITS OUTPUT. The
payload sent is four lines of invented payslip text defined below, not a
real document, and the payload is reported by SHAPE only - parameter
names, message roles, character counts - never by value.

Run: python verify/diagnose_openai_400.py
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass

import openai  # noqa: E402

from slyp.extraction import (  # noqa: E402
    _MODEL_NAME,
    _ModelExtract,
    _SYSTEM_PROMPT,
    _TOOL_NAME,
)

# Invented. Not a real payslip, and shaped only well enough to be a
# realistic request body.
SYNTHETIC = "\n".join(
    [
        "Pay Date: 28/08/2026",
        "Tax Code: 1257L     NI Table Letter A",
        "Total Gross Pay 1,000.00     Income Tax 100.00",
        "Net Pay 900.00",
    ]
)


def _describe(params: dict) -> None:
    """Shape only - never values from the document."""
    print("  request shape:")
    print(f"    model              : {params['model']}")
    print(f"    temperature        : {params.get('temperature')}")
    print(f"    top-level params   : {sorted(params.keys())}")
    print(f"    message roles      : {[m['role'] for m in params['messages']]}")
    for message in params["messages"]:
        print(f"      {message['role']:6} content: {len(message['content'])} chars")
    tool = params["tools"][0]
    print(f"    tools[0].type      : {tool['type']}")
    print(f"    tools[0].function  : {tool['function']['name']}")
    schema = tool["function"]["parameters"]
    print(f"    schema top keys    : {sorted(schema.keys())}")
    print(f"    schema properties  : {len(schema.get('properties', {}))}")
    print(f"    tool_choice        : {json.dumps(params['tool_choice'])}")


def main() -> int:
    client = openai.OpenAI()

    base = dict(
        model=_MODEL_NAME,
        temperature=0,
        messages=[
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": SYNTHETIC},
        ],
        tools=[
            {
                "type": "function",
                "function": {
                    "name": _TOOL_NAME,
                    "description": "Record the structured fields read off a UK payslip.",
                    "parameters": _ModelExtract.model_json_schema(),
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": _TOOL_NAME}},
    )

    print("=" * 70)
    print("ATTEMPT 1 - exactly what _call_openai_model() sends first")
    print("=" * 70)
    _describe(base)
    try:
        client.chat.completions.create(**base)
        print("\n  RESULT: 200 OK - no retry would happen on this model.")
        return 0
    except openai.BadRequestError as exc:
        print(f"\n  RESULT: HTTP {exc.status_code} {type(exc).__name__}")
        print(f"  error body: {json.dumps(getattr(exc, 'body', None), indent=2)}")

    print()
    print("=" * 70)
    print("ATTEMPT 2 - the retry, identical but for one added parameter")
    print("=" * 70)
    retry = {**base, "reasoning_effort": "none"}
    print(f"  added: reasoning_effort='none'")
    print(f"  user content identical to attempt 1: "
          f"{retry['messages'][1]['content'] == base['messages'][1]['content']}")
    response = client.chat.completions.create(**retry)
    calls = response.choices[0].message.tool_calls or []
    print(f"\n  RESULT: 200 OK, tool_calls: {[c.function.name for c in calls]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
