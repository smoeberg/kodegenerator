
import asyncio
from domain.model import Model, ModelProvider
from ai.client import AIClient


async def test_ai_client_generate():
    client = AIClient()
    model = Model(id="gpt-4o", name="GPT-4o", provider=ModelProvider.OPENAI)
    res = await client.generate_response(model, prompt="Write a hello world function in Python")
    assert "generated_function" in res or "Code implementation" in res

if __name__ == "__main__":
    asyncio.run(test_ai_client_generate())
    print("✅ AI Client Test Passed!")
