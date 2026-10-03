# LLM provider wrapper here.
# One function: chat(messages, tools) -> assistant message (content + tool_calls).
# Use the `openai` client with base_url from .env so any provider works.
import os
from openai import OpenAI
from dotenv import load_dotenv
 
load_dotenv()
 
client = OpenAI(
    base_url=os.getenv("BASE_URL", "https://api.openai.com/v1"),
    api_key=os.getenv("API_KEY"),
)
 
 
def chat(messages: list, tools: list) -> dict:
    """One model call. Returns the assistant message as a plain dict."""
    resp = client.chat.completions.create(
        model=os.getenv("MODEL", "openai/gpt-4o-mini"),
        messages=messages,
        tools=tools,
    )
    msg = resp.choices[0].message
 
    assistant_msg = {"role": "assistant", "content": msg.content or ""}
    if msg.tool_calls:
        assistant_msg["tool_calls"] = [
            {
                "id": tc.id,
                "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments},
            }
            for tc in msg.tool_calls
        ]
    return assistant_msg
