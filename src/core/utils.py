"""
Lab 11 — Helper Utilities
"""
from google.genai import types


class DummyContext:
    user_id = "student"

async def chat_with_agent(client, context, user_message: str, session_id=None):
    """Send a message to the agent and get the response.

    Args:
        client: The Langchain ChatNVIDIA instance
        context: A dictionary containing 'instruction' and 'plugins'
        user_message: Plain text message to send
        session_id: Optional session ID to continue a conversation

    Returns:
        Tuple of (response_text, session)
    """
    plugins = context.get('plugins', [])
    instruction = context.get('instruction', "")
    
    # 1. Run input guardrails
    user_content = types.Content(role="user", parts=[types.Part.from_text(text=user_message)])
    invocation_context = DummyContext()
    
    for plugin in plugins:
        if hasattr(plugin, 'on_user_message_callback'):
            result = await plugin.on_user_message_callback(
                invocation_context=invocation_context, 
                user_message=user_content
            )
            if result is not None:
                # Blocked by input guardrail!
                return result.parts[0].text, None
                
    # 2. Call Langchain ChatNVIDIA
    from langchain_core.messages import SystemMessage, HumanMessage
    messages = [
        SystemMessage(content=instruction),
        HumanMessage(content=user_message)
    ]
    
    final_response_text = ""
    # ChatNVIDIA might support astream or sync stream
    try:
        async for chunk in client.astream(messages):
            if hasattr(chunk, "additional_kwargs") and "reasoning_content" in chunk.additional_kwargs:
                pass # Print reasoning if desired
            if chunk.content:
                final_response_text += chunk.content
    except (NotImplementedError, AttributeError):
        for chunk in client.stream(messages):
            if hasattr(chunk, "additional_kwargs") and "reasoning_content" in chunk.additional_kwargs:
                print(chunk.additional_kwargs["reasoning_content"], end="", flush=True)
            if chunk.content:
                final_response_text += chunk.content
            
    # 3. Create dummy llm_response for output guardrails
    llm_response = type("DummyLLMResponse", (), {
        "content": types.Content(role="model", parts=[types.Part.from_text(text=final_response_text)])
    })
    
    # 4. Run output guardrails
    for plugin in plugins:
        if hasattr(plugin, 'after_model_callback'):
            llm_response = await plugin.after_model_callback(
                callback_context=None,
                llm_response=llm_response
            )
            
    # 5. Extract final text
    final_text = ""
    if hasattr(llm_response, "parts"): # returned a types.Content directly
        parts = llm_response.parts
    elif hasattr(llm_response, "content") and llm_response.content: # returned DummyLLMResponse
        parts = llm_response.content.parts
    else:
        parts = []

    for part in parts:
        if hasattr(part, "text") and part.text:
            final_text += part.text

    return final_text, None
