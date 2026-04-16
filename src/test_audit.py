import asyncio
from core.config import setup_api_key
from core.utils import chat_with_agent
from agents.agent import create_protected_agent
from testing.audit_log import AuditLogPlugin

async def main():
    setup_api_key()
    audit_plugin = AuditLogPlugin()
    # Add some print debugs
    print("Agent creation...")
    agent, runner = create_protected_agent([audit_plugin])
    
    print("Testing safe query...")
    resp, _ = await chat_with_agent(agent, runner, "What is the savings interest rate?")
    print("Response:", resp)
    print("Audit Log pending:", audit_plugin._pending)
    print("Audit Log logs:", audit_plugin.logs)

if __name__ == "__main__":
    asyncio.run(main())
