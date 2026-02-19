# Installation Guide: MemU Agent

This guide will help you set up the MemU Agent on your Windows machine.

## Prerequisites

1.  **Python 3.10 or higher**: [Download Python](https://www.python.org/downloads/)
    *   *Make sure to check "Add Python to PATH" during installation.*
2.  **OpenAI API Key**: [Get API Key](https://platform.openai.com/api-keys)

---

## Quick Install (Windows)

We've included a one-click setup script to make this easy.

1.  **Open the project folder** in File Explorer.
2.  Double-click `setup.bat`.
    *   This will create a virtual environment, install all dependencies, and create your config file.
3.  **Configure API Key**:
    *   Open the newly created `.env` file in Notepad or VS Code.
    *   Find the line `OPENAI_API_KEY=` and paste your key after `+`.
    *   Example: `OPENAI_API_KEY=sk-proj-12345...`

---

## Running the Agent

### 1. Web Interface (Recommended)
This launches the modern glassmorphism UI.

1.  Open a terminal in the project folder (or keep the one from setup open).
2.  Run:
    ```cmd
    venv\Scripts\python main.py
    ```
3.  The browser should open automatically to `http://localhost:8000`.

### 2. Terminal Mode (CLI)
If you prefer a hacker-style terminal chat:

1.  Run:
    ```cmd
    venv\Scripts\python main.py --cli
    ```

---

## Troubleshooting

-   **"python is not recognized"**: Reinstall Python and ensure "Add to PATH" is checked.
-   **Database Errors**: By default, the agent runs in `inmemory` mode to prevent database conflicts. 
    -   To enable persistent storage, edit `config/settings.py` or `.env` and change `DATABASE_PROVIDER` to `sqlite`, but ensure your system libraries are compatible.
-   **Missing Dependencies**: Run `setup.bat` again to repair the installation.

## Advanced: Switching Models

You can switch models directly in the Web UI dropdown, or via environment variables in `.env`:

```ini
# Default Provider
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-sonnet
```
