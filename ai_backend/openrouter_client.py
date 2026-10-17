"""
Minimal OpenRouter chat client (OpenAI-compatible API), shared by the Gemba Kaizen Agent and the cloud VLM.

- Optional JSON schema response; models that reject schemas (HTTP 400) are retried in plain JSON mode
  with the schema added to the system prompt
- Retries on rate limits / gateway errors (429, 502, 503, 504)
- Returns the text and OpenRouter's usage block (tokens and, when reported, cost in USD)
"""

import copy
import json
import os
import re
import time
from typing import Dict, List, Optional, Tuple

import requests

OPENROUTER_URL = os.getenv("OPENROUTER_URL", "https://openrouter.ai/api/v1/chat/completions")  # override: proxy / tests
RETRY_STATUS = {429, 502, 503, 504}
RETRY_DELAYS = (1.0, 3.0)


def parse_json(text: str) -> Dict:
    """JSON from a model answer, tolerating ```json fences and text around the object."""
    text = text.strip()
    fenced = re.search(r'```(?:json)?\s*(.*?)```', text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start, end = text.find('{'), text.rfind('}')
    return json.loads(text[start:end + 1] if start >= 0 else text)


def _post(body: Dict, headers: Dict, timeout: float):
    response = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=timeout)
    for delay in RETRY_DELAYS:
        if response.status_code not in RETRY_STATUS:
            break
        time.sleep(delay)
        response = requests.post(OPENROUTER_URL, headers=headers, json=body, timeout=timeout)
    return response


def chat(messages: List[Dict], model: str, api_key: str, schema: Optional[Dict] = None,
         schema_name: str = "response", timeout: float = 120, temperature: float = 0.2,
         max_tokens: Optional[int] = None, reasoning: Optional[Dict] = None) -> Tuple[str, Dict]:
    """One chat completion. Returns (message text, usage dict). Raises RuntimeError on HTTP errors."""
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/Celesca/U-HACKATHON26",
        "X-Title": "VALZ",
    }
    body: Dict = {"model": model, "temperature": temperature, "messages": messages}
    if max_tokens:
        body["max_tokens"] = max_tokens
    if reasoning is not None:
        body["reasoning"] = reasoning  # e.g. {"enabled": False}: thinking tokens would eat max_tokens and cut the answer
    if schema:
        body["response_format"] = {"type": "json_schema",
                                   "json_schema": {"name": schema_name, "strict": True, "schema": schema}}

    response = _post(body, headers, timeout)
    if response.status_code == 400 and "reasoning" in body:
        del body["reasoning"]  # this model or provider does not take the option
        response = _post(body, headers, timeout)
    if response.status_code == 400 and schema:
        # The model does not take JSON schemas: plain JSON mode, with the schema in the prompt
        body["response_format"] = {"type": "json_object"}
        body["messages"] = copy.deepcopy(messages)
        hint = "Return only a JSON object matching this JSON schema:\n" + json.dumps(schema)
        system = next((m for m in body["messages"] if m["role"] == "system" and isinstance(m["content"], str)), None)
        if system:
            system["content"] += "\n\n" + hint
        else:
            body["messages"].insert(0, {"role": "system", "content": hint})
        response = _post(body, headers, timeout)

    if response.status_code != 200:
        raise RuntimeError(f"OpenRouter HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()
    content = payload['choices'][0]['message']['content']
    return content or "", payload.get('usage') or {}
