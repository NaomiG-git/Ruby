import asyncio
import os
import json
import time
from config.settings import get_settings
from src.agent.controller import AgentController
from src.agent.state import ConversationState

async def run_test():
    print("--- Starting History Fix Verification ---")
    settings = get_settings()
    
    # Force a clean history file for test
    test_history_path = os.path.join(settings.data_dir, "history", "test_chat_history.json")
    if os.path.exists(test_history_path):
        os.remove(test_history_path)
    
    # Initialize controller with test history path
    # We'll monkeypatch the state persistence path
    agent = AgentController(settings)
    agent._state = ConversationState(
        session_id="test_session",
        user_id="test_user",
        persistence_path=test_history_path
    )
    
    print("1. Testing persistent process...")
    await agent.process("Hello, Ruby!", persist=True)
    
    with open(test_history_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        history = data.get("history", [])
        print(f"   History length: {len(history)}")
        if len(history) != 2:
            print("ERR: Expected 2 messages (user + assistant)")
            return
        if history[0]["content"] != "Hello, Ruby!":
            print("ERR: Incorrect message content")
            return

    print("2. Testing NON-persistent process (Background Task)...")
    await agent.process("Deep Reflection: Analyzing habits...", persist=False)
    
    with open(test_history_path, "r", encoding="utf-8") as f:
        data = json.load(f)
        history = data.get("history", [])
        print(f"   History length: {len(history)}")
        if len(history) != 2:
            print(f"ERR: Expected history to remain 2, but got {len(history)}")
            return
        print("OK: Background task correctly skipped persistence.")

    print("3. Verifying Scheduler last_run initialization...")
    from src.agent.scheduler import Scheduler
    sched = Scheduler()
    sched.add_job("Test Task", 3600)
    job = sched._jobs[0]
    now = time.time()
    diff = abs(now - job.last_run)
    print(f"   Job last_run diff: {diff:.4f}s")
    if diff > 5.0:
        print("ERR: last_run should be close to current time")
        return
    print("OK: Scheduler correctly initialized last_run to prevent immediate trigger.")

    print("\n--- All tests passed! ---")

if __name__ == "__main__":
    asyncio.run(run_test())
