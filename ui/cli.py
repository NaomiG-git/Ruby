"""Command-Line Interface for memU Agent."""

import asyncio
import sys
from typing import NoReturn

from rich.console import Console
from rich.markdown import Markdown
from rich.prompt import Prompt

from config.settings import get_settings
from src.agent.controller import AgentController


class CLI:
    """Simple terminal interface for the agent."""

    def __init__(self):
        self.console = Console()
        self.settings = get_settings()
        self.agent = None

    async def start(self) -> NoReturn:
        """Start the CLI loop."""
        self.console.print(f"[bold green]Initializing {self.settings.agent_name}...[/]")
        
        try:
            self.agent = AgentController(self.settings)
        except Exception as e:
            self.console.print(f"[bold red]Failed to initialize agent:[/]\n{e}")
            if "api_key" in str(e).lower():
                self.console.print("\n[yellow]Tip: Check your .env file and API keys.[/]")
            return

        self.console.print(f"\n[bold blue]Provider:[/] {self.agent.provider_name}")
        self.console.print("[dim]Type 'quit' to exit, 'help' for commands[/]\n")

        # Start background services
        asyncio.create_task(self.agent.start_service())

        while True:
            try:
                user_input = Prompt.ask("[bold green]You[/]")
                user_input = user_input.strip()

                if not user_input:
                    continue

                if user_input.lower() in ("quit", "exit"):
                    self.console.print("[yellow]Goodbye![/]")
                    break

                if await self._handle_command(user_input):
                    continue

                await self._chat(user_input)

            except KeyboardInterrupt:
                self.console.print("\n[yellow]Goodbye![/]")
                break
            except Exception as e:
                self.console.print(f"[bold red]Error:[/] {e}")

    async def _handle_command(self, user_input: str) -> bool:
        """Handle internal CLI commands. Returns True if command was handled."""
        cmd = user_input.lower().split()
        
        if cmd[0] == "help":
            self.console.print("\n[bold]Commands:[/]")
            self.console.print("  [cyan]switch <provider>[/]  Switch LLM (openai, anthropic, google, ollama)")
            self.console.print("  [cyan]clear[/]              Clear conversation history")
            self.console.print("  [cyan]memories[/]           (Not implemented in CLI view yet)")
            self.console.print("  [cyan]quit/exit[/]          Exit application\n")
            return True

        if cmd[0] == "switch":
            if len(cmd) < 2:
                self.console.print("[red]Usage: switch <provider>[/]")
                return True
            
            provider = cmd[1]
            try:
                self.agent.switch_provider(provider)
                self.console.print(f"[green]Switched to {provider}[/]")
            except Exception as e:
                self.console.print(f"[red]Failed to switch: {e}[/]")
            return True

        if cmd[0] == "clear":
            self.agent.clear_history()
            self.console.print("[green]History cleared.[/]")
            return True

        return False

    async def _chat(self, user_input: str) -> None:
        """Run a chat turn."""
        # Use status spinner for the agent "thinking" and acting
        with self.console.status("[bold green]Thinking...[/]", spinner="dots"):
            response = await self.agent.process(user_input)
            
        self.console.print(f"[bold blue]Agent[/]: {response}")
        self.console.print()  # Spacing
