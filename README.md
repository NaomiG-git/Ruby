# Ruby

Ruby is not just another chatbot — she is a highly capable, proactive AI life partner built for Windows. Built with [AntiGravity](https://antigravity.dev), Ruby combines long-term memory, vision intelligence, creative tools, video production, deep web research, and full file + email mastery into a single, always-on assistant that learns who you are over time.

---

## Overview

Ruby is a local-first, Windows-native AI assistant with a polished UI/UX and a modular skillset that expands over time. She uses dual-model reasoning (GPT-4o for complex tasks, GPT-4o-mini for efficient memory management) and automatically selects the right tools for the job — without you having to ask.

---

## What Ruby Can Do Today

### 🧠 Core Intelligence & Memory
- **Long-term memory** — powered by the [memU](https://github.com/cagostino/memu) framework; Ruby retains context and learns about you over time
- **Proactive reasoning** — dual-model logic: GPT-4o for deep thinking, GPT-4o-mini for fast, efficient memory operations
- **Tool-use mastery** — automatically selects from her full skillset to solve tasks without explicit instruction
- **Async-first performance** — built for responsive, non-blocking operation across all skills

### 🎨 UI / UX
Ruby ships with a purpose-built Windows interface designed for natural, fluid interaction:
- Clean, responsive chat UI with full conversation history
- Dedicated visual canvas workspace for rich content and live previews
- Real-time streaming responses
- Dark/light mode, customizable layout
- Keyboard shortcuts and accessibility support

### 👁️ Vision & Screen Intelligence
- **Screen capture** — sees your primary monitor via high-resolution screenshots; provides context-aware help for whatever you're working on
- **OCR (text extraction)** — reads text from images, documents, and screenshots using advanced Optical Character Recognition
- **Color analysis** — extracts dominant color palettes from any image, returning Hex, RGB, and pigment names (ideal for artists and designers)
- **File attachments** — attach documents, images, spreadsheets, PDFs, and more; Ruby reads and reasons over them

### 📽️ Video Production & Editing
- **Trim & concatenate** — cut and combine video clips
- **Audio & text overlays** — add voiceover, music, or caption tracks to video
- **Smart editing** — automatically removes silent "dead space" and visually static segments (e.g. loading screens)
- **Video analysis** — downloads and visually analyzes video from URLs (YouTube, Vimeo, etc.) frame-by-frame; answers questions about content

### 🎨 Creative & Design Tools
- **Web project creation** — generates complete web projects (HTML, CSS, JS) directly to your Desktop
- **Pinterest Pin Designer** — creates professional 2:3 Pinterest Pins with custom text overlays and branding
- **Canvas rendering** — pushes rich content, diagrams, and live application previews to her dedicated visual workspace

### 🌐 Web & Research
- **Smart search** — searches the web via DuckDuckGo with a visual fallback browser to bypass bot detection
- **Deep browsing** — reads and summarizes full text from articles, blogs, and documentation pages
- **Web login sessions** — opens a visible browser for you to log into sites (e.g. Substack), saves the authenticated session for private later access

### 📧 Communication & Email
- **Gmail** — send, read, list folders, and delete emails
- **Outlook** — send, read, list folders, and delete emails
- Full email management without leaving Ruby

### 🗂️ File & System Mastery
- **File management** — list, create, read, write, search, move, and delete local files
- **App launcher** — opens applications on your behalf
- **Desktop integration** — saves generated projects and files directly to your Windows Desktop

---

## Coming Soon — Expanding Ruby's Reach

### Multi-Channel Messaging
Interact with Ruby across the channels you already use:

| Channel | Status |
|---|---|
| WhatsApp | Planned |
| Telegram | Planned |
| Discord | Planned |
| Slack | Planned |
| Signal | Planned |
| Microsoft Teams | Planned |
| SMS (Windows-paired Android) | Planned |

### AI Model Support
Ruby connects to AI providers using your **existing subscription** — no API keys, no separate billing. Authentication is handled via OAuth PKCE — sign in once in a browser, tokens stored in the encrypted vault.

| Provider | Auth Method | Subscription | Models |
|---|---|---|---|
| **OpenAI (ChatGPT)** | OAuth PKCE | ChatGPT Plus / Pro | gpt-4o, gpt-4o-mini, o3, o4-mini |
| **Google (Gemini 3)** | Google OAuth 2.0 | Gemini Advanced / Google One AI Premium | gemini-3-ultra, gemini-3-flash, gemini-2-flash |
| Venice (privacy-first, optional) | API key | Venice subscription | — |
| vLLM (self-hosted, optional) | Local — no auth | Self-hosted | Any |

> **No API keys needed** for ChatGPT or Gemini. Sign in once and Ruby handles token refresh automatically.

Switch models at any time with the `/model` command:
```
/model list                  — see all available models
/model gpt-4o                — switch primary model
/model gemini-3-ultra        — switch to Gemini 3 Ultra
/model fallback gemini-flash — set fallback if primary fails
/model status                — show current model + session stats
```

### Scheduling & Automation
- **Cron-based scheduled jobs** — daily briefings, automated reports, recurring tasks
- **Smart reminders** — set reminders in natural language; Ruby follows up proactively
- **Webhook triggers** — inbound (external services trigger Ruby) and outbound (Ruby calls external services)
- **Event-driven automation** — trigger flows from Gmail, calendar events, file changes, or system events
- **Windows Task Scheduler integration** — Ruby jobs run even when the UI is closed
- **Automation chains** — link multiple skills into multi-step workflows with conditional logic

### Browser Automation
- Dedicated Chromium instance with CDP control
- Form filling, file uploads, agent-driven browser sessions
- Sandboxed per-session browser profiles

### Skills Platform
- Modular, installable skill packages (`SKILL.md` based)
- Community skills registry (coming soon)
- CLI: `ruby skill install <name>`, `ruby skill update`, `ruby skill list`

---

## Security — Ruby vs. OpenClaw

Ruby's security model is designed to address known weaknesses in similar open-source gateways (including OpenClaw):

| Area | OpenClaw | Ruby |
|---|---|---|
| **AI auth** | API keys stored in plaintext ⚠️ (HIGH risk) | OAuth sign-in with your ChatGPT / Gemini subscription — no API keys needed |
| **Credential storage** | Plaintext on disk ⚠️ | AES-256-GCM encrypted vault, Windows DPAPI-backed |
| **Token rotation** | Not implemented ⚠️ | OAuth refresh tokens automatically rotated on use |
| **Identity verification** | Phone/username only — spoofable (medium risk) | Cryptographic peer identity verification (HMAC-signed pairing tokens) |
| **Pairing window** | 30-second open window — interception risk | Time-limited signed QR/token with replay protection |
| **Auth modes** | token / password / trusted-proxy | OAuth (Google / OpenAI) + Windows Hello / biometric unlock |
| **Exec approval** | Unix socket approval | Named pipe approval with signed request/response (Windows-native) |
| **Sandboxing** | Docker (non-main sessions) | Docker + Windows AppContainer for non-main sessions |
| **Audit tooling** | `openclaw security audit` | `ruby security audit [--deep] [--fix] [--json]` + Windows Event Log integration |
| **DM access policy** | pairing / allowlist / open / disabled | Same, with additional cryptographic allowlist signing |
| **Threat model** | MITRE ATLAS documented | MITRE ATLAS + Windows-specific threat extensions |

### Credential Storage
All OAuth session tokens and channel credentials are stored in an encrypted vault — never in plaintext:
- **Encryption:** AES-256-GCM
- **Key derivation:** Windows DPAPI for seamless unlock (no master password needed on your own machine)
- **Location:** `%APPDATA%\Ruby\vault\`
- **Token rotation:** OAuth refresh tokens are automatically rotated on use
- **No API keys stored** for ChatGPT or Gemini — only short-lived OAuth session tokens

### DM Access Policies
| Mode | Description |
|---|---|
| `pairing` | Cryptographically signed approvals stored in the encrypted vault |
| `allowlist` | Static allowlist with HMAC-signed entries |
| `open` | Requires explicit double opt-in + reason logging |
| `disabled` | Block all DMs (default) |

Run `ruby doctor` to surface risky configurations.
Run `ruby security audit` for a full audit with optional auto-fix.

---

## Getting Started

> **Platform:** Windows 10/11 (64-bit) required.

1. Clone the repository:
   ```sh
   git clone https://github.com/NaomiG-git/Ruby.git
   cd Ruby
   ```

2. Install dependencies:
   ```sh
   npm install
   ```

3. Initialize Ruby (first-run setup):
   ```sh
   ruby onboard
   ```

4. Start the gateway:
   ```sh
   ruby gateway
   ```

---

## Project Structure

```
Ruby/
├── core/           # Dual-model reasoning engine (GPT-4o + GPT-4o-mini)
├── memory/         # Long-term memory (memU framework)
├── vision/         # Screen capture, OCR, color analysis
├── video/          # Video editing, smart trimming, frame analysis
├── canvas/         # Visual workspace renderer
├── design/         # Web project creator, Pinterest Pin Designer
├── search/         # DuckDuckGo search, deep browsing, login sessions
├── email/          # Gmail + Outlook integration
├── files/          # Local file management + app launcher
├── models/         # 🤖 AI model support
│   ├── __init__.py        # Module exports
│   ├── openai_client.py   # ChatGPT (Plus/Pro) via OAuth PKCE — no API key
│   ├── gemini_client.py   # Gemini 3 via Google OAuth 2.0 — no API key
│   └── router.py          # Unified router: fallback chain, /model switching, history
├── security/       # 🔒 Security module
│   ├── __init__.py
│   ├── vault.py           # AES-256-GCM encrypted credential vault (DPAPI-backed)
│   ├── identity.py        # HMAC-SHA256 signed pairing tokens + peer allowlist
│   ├── windows_hello.py   # Windows Hello biometric / PIN vault unlock
│   └── audit.py           # Security audit CLI (--deep, --fix, --json)
├── channels/       # Messaging channel adapters (planned)
├── scheduling/     # Cron jobs, reminders, webhooks, automation chains (planned)
├── browser/        # CDP browser automation (planned)
└── docs/           # Documentation and threat model
```

---

## Roadmap

**Already built:**
- [x] UI/UX — polished Windows-native interface with canvas workspace
- [x] Long-term memory — memU framework, learns about you over time
- [x] Proactive reasoning — dual-model GPT-4o + GPT-4o-mini
- [x] Screen capture & awareness — sees your primary monitor in real time
- [x] OCR — extracts text from images, documents, screenshots
- [x] Color analysis — Hex, RGB, pigment names from any image
- [x] Video editing — trim, concat, audio/text overlays, smart dead-space removal
- [x] Video analysis — frame-by-frame analysis of YouTube, Vimeo, and more
- [x] Web project creation — generates full HTML/CSS/JS projects to Desktop
- [x] Pinterest Pin Designer — 2:3 pins with text overlays and branding
- [x] Canvas rendering — rich content, diagrams, live app previews
- [x] Smart web search — DuckDuckGo + visual fallback browser
- [x] Deep browsing — full article/doc reading and summarization
- [x] Web login sessions — authenticated browser sessions saved for later
- [x] Gmail & Outlook — send, read, manage folders, delete
- [x] File mastery — list, create, read, write, search, move, delete, launch apps
- [x] ChatGPT + Gemini 3 via OAuth (your existing subscription)
- [x] Encrypted credential vault — `security/vault.py` (AES-256-GCM + Windows DPAPI)
- [x] HMAC peer identity verification — `security/identity.py` (signed tokens + allowlist)
- [x] Windows Hello biometric unlock — `security/windows_hello.py`
- [x] Security audit CLI — `security/audit.py` (`python -m security.audit [--deep] [--fix] [--json]`)
- [x] AI model module — `models/` (OpenAI OAuth, Gemini OAuth, router, fallback chain, `/model` command)

**In progress / planned:**
- [ ] Multi-channel messaging (WhatsApp, Telegram, Discord, Slack, Signal, Teams, SMS)
- [ ] Advanced scheduling — cron jobs, smart reminders, recurring tasks
- [ ] Event-driven automation chains with webhook triggers
- [ ] Windows Task Scheduler integration
- [ ] Browser automation (CDP — dedicated Chromium, form actions, uploads)
- [ ] Skills platform + community registry
- [ ] Multi-agent routing with Docker sandboxing
- [ ] MITRE ATLAS threat model documentation

---

## Built With

- **AntiGravity** — core AI foundation
- **memU** — long-term memory framework
- **GPT-4o + GPT-4o-mini** — dual-model reasoning and memory management
- **OpenAI OAuth PKCE** — ChatGPT Plus/Pro subscription sign-in (`models/openai_client.py`)
- **Google OAuth 2.0 PKCE** — Gemini 3 / Google One AI Premium sign-in (`models/gemini_client.py`)
- **Windows DPAPI / AES-256-GCM** — encrypted credential vault (`security/vault.py`)
- **HMAC-SHA256** — cryptographic peer identity verification (`security/identity.py`)
- **Windows Hello (WinRT)** — biometric vault unlock (`security/windows_hello.py`)
- **DuckDuckGo + Playwright** — smart search and visual browser fallback
- **Gmail API + Outlook API** — email integration
- **FFmpeg** — video editing, trimming, overlays
- **httpx** — async HTTP for model API calls
- **Electron** — Windows desktop UI
- **Inspired by** [OpenClaw](https://github.com/openclaw/openclaw) — with a security-first redesign

---

## Contributing

Contributions are welcome! Please open issues or submit pull requests. For security vulnerabilities, please use private disclosure (see `SECURITY.md`).

## License

*Specify license here.*
