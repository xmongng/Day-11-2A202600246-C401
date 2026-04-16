import asyncio
import os
from langchain_nvidia_ai_endpoints import ChatNVIDIA
from langchain_core.messages import HumanMessage

async def main():
    client = ChatNVIDIA(
        model="openai/gpt-oss-120b",
        api_key=os.environ.get("NVIDIA_API_KEY", ""),
        temperature=1,
        max_tokens=100
    )
    print("Testing astream...")
    try:
        async for chunk in client.astream([HumanMessage(content="Hello")]):
            print(repr(chunk.content))
    except Exception as e:
        print("Error:", e)

    print("Testing stream...")
    for chunk in client.stream([HumanMessage(content="Hello")]):
        print(repr(chunk.content))

import dotenv
dotenv.load_dotenv("/Users/mong/Documents/ComputerScience/AI4SE/AI_ThucChien/Day-11-2A202600246-C401/src/.env")
asyncio.run(main())
