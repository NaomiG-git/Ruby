# Ruby: The Proactive AI Life Partner 💎✨

Ruby is a deeply personalized, proactive AI companion that works for you 24/7. Built on the modular memU framework, she combines long-term memory with cutting-edge vision and tool-use capabilities to manage your tasks, emails, and files while you sleep.

## Features

- 🧠 **Long-term Memory**: Powered by memU for persistent, proactive memory
- 🔄 **Multi-Provider LLM**: Switch between OpenAI, Claude, Gemini, or local models
- 💰 **Cost-Optimized**: Uses gpt-4o-mini for memory operations, gpt-4o for reasoning
- 📦 **Modular Architecture**: Clean separation of concerns for easy extension
- 🚀 **Async First**: Built for performance with async/await throughout

## Quick Start

### Prerequisites

- Python 3.13+
- OpenAI API key

### Installation

```bash
# Clone or navigate to the project
cd memu-agent

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Copy environment template and add your API keys
cp .env.example .env
# Edit .env and add your OPENAI_API_KEY
```

### Running the Agent

```bash
python main.py
```

### CLI Commands

| Command | Description |
|---------|-------------|
| `quit` or `exit` | Exit the agent |
| `switch <provider>` | Switch LLM provider (openai, anthropic, google, ollama) |
| `clear` | Clear conversation history |
| `memories` | Show current memory categories |
| `help` | Show available commands |

## Project Structure

```
memu-agent/
├── src/                # Core Python Backend
│   ├── agent/          # Agent Logic & Controller
│   ├── memory/         # Long-term Memory Layer
│   ├── llm/            # Multi-Provider LLM logic
│   └── infrastructure/ # Logging and Utilities
├── ui/                 # CLI & Web Interface Code
├── desktop/            # Electron Wrapper
├── data/               # Local Database & Video Cache (Ignored)
├── main.py             # Entry point
└── requirements.txt    # dependencies
```

## Configuration

### Model Selection

The agent uses a hybrid model approach for cost optimization:

| Task | Model | Reason |
|------|-------|--------|
| Agent reasoning | gpt-4o | Best quality for user-facing responses |
| Memory extraction | gpt-4o-mini | Cost-effective for routine tasks |
| Embeddings | text-embedding-3-small | Fast and accurate |

### Switching Providers

```python
# Via environment
LLM_PROVIDER=anthropic
LLM_MODEL=claude-3-5-sonnet-20241022

# Via CLI
> switch anthropic

# Via code
from src.llm.factory import ProviderFactory
llm = ProviderFactory.create("anthropic", model="claude-3-5-sonnet-20241022")
```

## 🤝 Contributing

Ruby is an open project! If you're a developer who wants to help make Ruby even more proactive:

1.  **Fork** the repo.
2.  Create a **feature branch** (`git checkout -b feature/AmazingFeature`).
3.  **Commit** your changes (`git commit -m 'Add some AmazingFeature'`).
4.  **Push** to the branch (`git push origin feature/AmazingFeature`).
5.  Open a **Pull Request**.

## 📜 License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.
