# ai/client.py (Udvidet)
class AIClient:
    # ... (Forrige kode)

    async def _call_mistral(
        self,
        model: Model,
        prompt: str,
        system_message: Optional[str] = None,
        messages: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """Kald Mistral API."""
        url = f"{model.api_url}/chat/completions" if model.api_url else "https://api.mistral.ai/v1/chat/completions"

        # Byg messages
        if messages:
            msg = messages
        else:
            msg = [{"role": "system", "content": system_message or "You are a helpful assistant."}]
            msg.append({"role": "user", "content": prompt})

        payload = {
            "model": model.id,
            "messages": msg,
            "temperature": temperature,
            "max_tokens": max_tokens or model.max_tokens,
            **kwargs
        }

        headers = {
            "Authorization": f"Bearer {model.api_key}",
            "Content-Type": "application/json"
        }

        response = await self.http_client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]

    async def _call_google(
        self,
        model: Model,
        prompt: str,
        system_message: Optional[str] = None,
        messages: Optional[List[Dict]] = None,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
        **kwargs
    ) -> str:
        """Kald Google Gemini API."""
        url = f"{model.api_url}/models/{model.id}:generateContent" if model.api_url else f"https://generativelanguage.googleapis.com/v1beta/models/{model.id}:generateContent"

        # Byg messages
        if messages:
            msg = [{"role": "user", "parts": [{"text": m["content"]}]} for m in messages]
        else:
            msg = [{"role": "user", "parts": [{"text": prompt}]}]

        if system_message:
            msg.insert(0, {"role": "system", "parts": [{"text": system_message}]})

        payload = {
            "contents": msg,
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens or model.max_tokens
            },
            **kwargs
        }

        headers = {
            "Authorization": f"Bearer {model.api_key}",
            "Content-Type": "application/json"
        }

        response = await self.http_client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

        # Håndter mulige fejl
        if "error" in data:
            raise Exception(data["error"]["message"])

        return data["candidates"][0]["content"]["parts"][0]["text"]
