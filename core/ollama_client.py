import json
import urllib.error
import urllib.request

OLLAMA_URL = "http://127.0.0.1:11434/api/generate"


class OllamaClient:
    """Local-only Ollama client. Talks exclusively to 127.0.0.1 -- never
    configured to point anywhere else. temperature=0 and format="json" push
    the model toward strict, parseable, non-creative span output, matching
    the "detector only, never rewriter" contract of core/llm_detector.py.
    """

    def __init__(self, model: str = "qwen2.5:7b-instruct", timeout: float = 120.0):
        self.model = model
        self.timeout = timeout

    def generate(self, prompt: str) -> str:
        payload = {
            "model": self.model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        }
        req = urllib.request.Request(
            OLLAMA_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ConnectionError(f"无法连接本地 Ollama 服务: {e}") from e
        return body.get("response", "")
