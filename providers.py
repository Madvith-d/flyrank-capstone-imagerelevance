"""Provider adapters for deterministic local, Gemini, and Ollama execution."""
from __future__ import annotations

import base64
import json
import os
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from app import CORPUS, ImageTags, embed


@dataclass
class Call:
    value: object
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0


class LocalProvider:
    """Reference provider: no network or credentials, but the same validated call contract."""

    def classify(self, image_path: str) -> Call:
        image_id = Path(image_path).stem
        record = next((item for item in CORPUS if item[0] == image_id), None)
        if record is None:
            raise FileNotFoundError(image_path)
        _, subject, caption, attributes, confidence = record
        tags = ImageTags.validate({
            "subject": subject,
            "category": "animal",
            "attributes": attributes,
            "caption": caption,
            "confidence": confidence,
        })
        return Call(tags, "local-reference")

    def embed(self, text: str) -> Call:
        return Call(embed(text), "local-hash")


class GeminiProvider:
    def __init__(self):
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise RuntimeError("Gemini requires google-genai; install requirements.txt") from exc
        if not os.getenv("GEMINI_API_KEY"):
            raise RuntimeError("GEMINI_API_KEY is required when VISION_PROVIDER=gemini")
        self.genai, self.types = genai, types
        retry_options = types.HttpRetryOptions(attempts=2, initial_delay=0.2, max_delay=1.0, http_status_codes=[408, 429, 500, 502, 503, 504])
        self.client = genai.Client(api_key=os.environ["GEMINI_API_KEY"], http_options=types.HttpOptions(timeout=30000, retry_options=retry_options))
        self.vision_model = os.getenv("GEMINI_VISION_MODEL", "gemini-2.5-flash")
        self.embedding_model = os.getenv("GEMINI_EMBEDDING_MODEL", "gemini-embedding-001")

    def classify(self, image_path: str) -> Call:
        path = Path(image_path)
        if not path.is_file():
            raise FileNotFoundError(image_path)
        mime = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}.get(path.suffix.lower(), "image/jpeg")
        response = self.client.models.generate_content(
            model=self.vision_model,
            contents=[self.types.Part.from_bytes(data=path.read_bytes(), mime_type=mime), "Classify this image for an image library."],
            config=self.types.GenerateContentConfig(response_mime_type="application/json", response_schema=ImageTags.schema()),
        )
        tags = ImageTags.validate(json.loads(response.text))
        return Call(tags, self.vision_model)

    def embed(self, text: str) -> Call:
        response = self.client.models.embed_content(model=self.embedding_model, contents=text, config=self.types.EmbedContentConfig(task_type="SEMANTIC_SIMILARITY", output_dimensionality=768))
        return Call(response.embeddings[0].values, self.embedding_model)


class OllamaProvider:
    def __init__(self):
        self.base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
        self.vision_model = os.getenv("OLLAMA_VISION_MODEL", "llava")
        self.embedding_model = os.getenv("OLLAMA_EMBEDDING_MODEL", "all-minilm")

    def _post(self, path, payload):
        request = urllib.request.Request(self.base + path, json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=120) as response:
            return json.load(response)

    def classify(self, image_path: str) -> Call:
        data = base64.b64encode(Path(image_path).read_bytes()).decode()
        response = self._post("/api/generate", {"model": self.vision_model, "prompt": "Return only JSON with subject, category, attributes, caption, confidence for this image.", "images": [data], "format": "json", "stream": False})
        return Call(ImageTags.validate(json.loads(response["response"])), self.vision_model)

    def embed(self, text: str) -> Call:
        response = self._post("/api/embed", {"model": self.embedding_model, "input": text})
        return Call(response["embeddings"][0], self.embedding_model)


def provider():
    name = os.getenv("VISION_PROVIDER", "local").lower()
    return {"local": LocalProvider, "gemini": GeminiProvider, "ollama": OllamaProvider}.get(name, LocalProvider)()


__all__ = ["Call", "LocalProvider", "GeminiProvider", "OllamaProvider", "provider"]
