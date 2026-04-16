import asyncio
from defense_pipeline import test_safe_queries, create_pipeline
from core.config import setup_api_key

async def main():
    setup_api_key()
    agent, runner, plugins, monitor = create_pipeline()
    audit_log = plugins["audit_log"]
    
    await test_safe_queries(agent, runner, audit_log)
    print("Logs inside audit log:", audit_log.logs)

if __name__ == "__main__":
    asyncio.run(main())
