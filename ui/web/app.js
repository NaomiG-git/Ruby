// Global error logging for debugging in Electron
window.onerror = function (message, source, lineno, colno, error) {
    const errorMsg = `[JS Error] ${message} at ${source}:${lineno}:${colno}`;
    console.error(errorMsg);
    const history = document.getElementById('chat-history');
    if (history) {
        const div = document.createElement('div');
        div.className = 'message system';
        div.innerHTML = `<div class="content" style="color: #ef4444;">${errorMsg}</div>`;
        history.appendChild(div);
    }
    return false;
};

document.addEventListener('DOMContentLoaded', () => {
    // DOM Elements
    const chatHistory = document.getElementById('chat-history');
    const userInput = document.getElementById('user-input');
    const sendBtn = document.getElementById('send-btn');
    const clearBtn = document.getElementById('clear-btn');
    const providerSelect = document.getElementById('provider-select');
    const modelSelect = document.getElementById('model-select');
    const modelSection = document.getElementById('model-section');
    const hybridRoutingCheck = document.getElementById('hybrid-routing-check');
    const currentModelDisplay = document.getElementById('current-model-display');
    const voiceToggle = document.getElementById('voice-toggle');
    const voiceSelect = document.getElementById('voice-select');
    const refreshVoicesBtn = document.getElementById('refresh-voices-btn');
    const speechOverlay = document.getElementById('speech-overlay');
    const subtitleText = document.getElementById('subtitle-text');

    const canvasPanel = document.getElementById('canvas-panel');
    const canvasContent = document.getElementById('canvas-content');
    const canvasToggleBtn = document.getElementById('canvas-toggle-btn');
    const closeCanvasBtn = document.getElementById('close-canvas-btn');

    const attachBtn = document.getElementById('attach-btn');
    const imageInput = document.getElementById('image-input');
    const imagePreviewContainer = document.getElementById('image-preview-container');
    const clearInputBtn = document.getElementById('clear-input-btn');

    // Clear Input Logic
    userInput.addEventListener('input', () => {
        if (userInput.value.trim() !== '') {
            clearInputBtn.classList.remove('hidden');
        } else {
            clearInputBtn.classList.add('hidden');
        }
        userInput.style.height = 'auto';
        userInput.style.height = (userInput.scrollHeight) + 'px';
    });

    clearInputBtn.addEventListener('click', () => {
        userInput.value = '';
        userInput.focus();
        userInput.style.height = 'auto';
        clearInputBtn.classList.add('hidden');
    });
    async function loadConfig() {
        try {
            const response = await fetch('/api/config');
            const config = await response.json();

            if (config.hybrid_routing && hybridRoutingCheck) {
                hybridRoutingCheck.checked = true;
                console.log("Hybrid routing enabled by default config.");
            }

            if (config.provider && providerSelect) {
                providerSelect.value = config.provider;
            }

            if (config.model && modelSelect) {
                // Ensure model is in the list
                const exists = Array.from(modelSelect.options).some(o => o.value === config.model);
                if (exists) modelSelect.value = config.model;
            }

        } catch (error) {
            console.error("Failed to load config:", error);
            // Don't show system error for initial config load, but log it
            if (chatHistory) {
                const div = document.createElement('div');
                div.className = 'message system';
                div.innerHTML = `<div class="content" style="color: #f59e0b;">Ready to start? (Connection to Ruby engine pending...)</div>`;
                chatHistory.appendChild(div);
            }
        }
    }
    loadConfig();

    // Canvas Toggling
    function toggleCanvas(show = null) {
        console.log("toggleCanvas called with:", show);
        if (show === null) {
            canvasPanel.classList.toggle('hidden');
        } else if (show) {
            canvasPanel.classList.remove('hidden');
            canvasPanel.style.display = 'flex'; // Force visibility
        } else {
            canvasPanel.classList.add('hidden');
            canvasPanel.style.display = 'none';
        }
    }

    if (canvasToggleBtn) canvasToggleBtn.onclick = () => toggleCanvas();
    if (closeCanvasBtn) closeCanvasBtn.onclick = () => toggleCanvas(false);

    // Default models for each provider
    const providerModels = {
        'openai': ['gpt-4o', 'gpt-4o-mini', 'o1', 'o1-mini'],
        'anthropic': ['claude-3-5-sonnet-20241022', 'claude-3-opus-20240229', 'claude-3-haiku-20240307', 'claude-sonnet-4-6'],
        'google': ['gemini-2.0-flash', 'gemini-1.5-pro-latest', 'gemini-1.5-flash-latest'],
        'ollama': ['llama3.2', 'function-gemma']
    };

    // State
    let isProcessing = false;
    let synth = window.speechSynthesis;
    let voices = [];
    let isVoiceEnabled = false;
    let pendingImages = [];

    // Load available voices
    function populateVoiceList() {
        console.log("Attempting to populate voice list...");
        if (!synth) {
            console.error("Speech Synthesis not supported in this browser.");
            if (voiceSelect) voiceSelect.innerHTML = '<option value="">Not Supported</option>';
            return false;
        }

        voices = synth.getVoices();
        console.log("Found voices:", voices.map(v => `${v.name} (${v.lang})`));

        // DUMMY TRICK: Some Browsers (Chrome/Edge) need a nudge to load voices
        if (voices.length === 0) {
            const dummy = new SpeechSynthesisUtterance("");
            synth.speak(dummy);
            voices = synth.getVoices();
        }

        if (voices.length === 0) {
            console.log("Voices still empty. Browser: " + navigator.userAgent);
            return false;
        }

        console.log(`Successfully loaded ${voices.length} voices.`);
        if (voiceSelect) {
            voiceSelect.innerHTML = '';
            let bestVoiceIndex = -1;

            // Priority keywords for a female assistant named Ruby
            const femaleKeywords = ["ruby", "zira", "female", "woman", "samantha", "victoria", "hazel", "susan", "jane", "annnie", "linda", "google", "en-gb", "en-au"];
            const maleKeywords = ["david", "mark", "george", "male", "man", "sean"];

            voices.forEach((voice, i) => {
                const nameLower = voice.name.toLowerCase();

                // SKIP MALE VOICES: If the user says they only want Ruby to have a female identity
                if (maleKeywords.some(kw => nameLower.includes(kw))) {
                    return; // Skip adding this to the dropdown
                }

                const option = document.createElement('option');
                option.textContent = `${voice.name} (${voice.lang})`;
                option.value = i;

                // Try to find the best matching female voice
                // 1. High Priority: Direct keyword match
                if (bestVoiceIndex === -1 && femaleKeywords.some(kw => nameLower.includes(kw))) {
                    console.log(`Excellent female match found: ${voice.name} (Index ${i})`);
                    bestVoiceIndex = i;
                }

                // 2. Fallback: If no best voice yet, and it's default
                if (voice.default && bestVoiceIndex === -1) {
                    console.log(`Using default voice as fallback: ${voice.name} (Index ${i})`);
                    bestVoiceIndex = i;
                }

                voiceSelect.appendChild(option);
            });

            // 3. Final Fallback: If still nothing, pick the first non-male voice in the list
            if (bestVoiceIndex === -1) {
                for (let i = 0; i < voices.length; i++) {
                    const nameLower = voices[i].name.toLowerCase();
                    if (!maleKeywords.some(kw => nameLower.includes(kw))) {
                        console.log(`Last resort: Picked first non-male voice: ${voices[i].name}`);
                        bestVoiceIndex = i;
                        break;
                    }
                }
            }

            if (bestVoiceIndex !== -1) {
                console.log(`Final selected voice index: ${bestVoiceIndex}`);
                voiceSelect.value = bestVoiceIndex;
                // Force triggering any change event if needed
                voiceSelect.dispatchEvent(new Event('change'));
            } else if (voices.length > 0) {
                voiceSelect.selectedIndex = 0;
            }
        }
        return true;
    }

    // Persistent polling for voices
    let pollCount = 0;
    const interval = setInterval(() => {
        pollCount++;
        if (populateVoiceList() || pollCount > 20) {
            clearInterval(interval);
            if (voices.length === 0) {
                console.warn("Giving up on automatic voice loading after 10 seconds.");
                if (voiceSelect) voiceSelect.innerHTML = '<option value="">(No voices found)</option>';
            }
        }
    }, 500);

    if (synth && synth.onvoiceschanged !== undefined) {
        synth.onvoiceschanged = () => {
            console.log("onvoiceschanged event triggered.");
            populateVoiceList();
        };
    }

    function speak(text) {
        if (!isVoiceEnabled || !text) return;

        // Stop current speech
        synth.cancel();

        // Strip markdown for cleaner speech (and better subtitles)
        const cleanText = text.replace(/[#*`_~\[\]]/g, '').replace(/<[^>]*>/g, '');

        const utter = new SpeechSynthesisUtterance(cleanText);
        const selectedVoiceIndex = voiceSelect.value;
        if (voices[selectedVoiceIndex]) {
            console.log(`Speaking with voice: ${voices[selectedVoiceIndex].name}`);
            utter.voice = voices[selectedVoiceIndex];
        } else {
            console.warn(`No voice found at index: ${selectedVoiceIndex}`);
        }

        // Show subtitles
        if (speechOverlay && subtitleText) {
            subtitleText.textContent = cleanText;
            speechOverlay.classList.remove('hidden');

            utter.onend = () => speechOverlay.classList.add('hidden');
            utter.onerror = () => speechOverlay.classList.add('hidden');
        }

        utter.rate = 1.1; // Slightly faster
        utter.pitch = 1.05; // Slightly higher pitch for clarity
        synth.speak(utter);
    }

    // Load initial config
    async function init() {
        try {
            // Add timestamp to prevent caching
            const res = await fetch('/api/config?t=' + Date.now());
            const data = await res.json();

            const provider = data.provider.toLowerCase();
            console.log(`Init: Provider=${provider}, Model=${data.model}`);

            // Update options first
            updateModelOptions(provider, data.model);

            // Then force selection
            providerSelect.value = provider;

            // Updates display
            currentModelDisplay.textContent = data.model;

            // Check if hybrid routing is enabled in settings (we'll need to add this to API)
            if (data.hybrid_routing) {
                hybridRoutingCheck.checked = true;
            }
        } catch (err) {
            console.error('Failed to initialize app', err);
        }
    }
    init();

    // Updates model dropdown based on provider
    function updateModelOptions(provider, currentModel) {
        modelSelect.innerHTML = '';
        let options = [];

        if (provider === 'openai') {
            options = [
                { value: 'gpt-4o', label: 'GPT-4o' },
                { value: 'gpt-4-turbo', label: 'GPT-4 Turbo' },
                { value: 'gpt-3.5-turbo', label: 'GPT-3.5 Turbo' }
            ];
        } else if (provider === 'google') {
            options = [
                { value: 'gemini-2.0-flash', label: 'Gemini 2.0 Flash' },
                { value: 'gemini-2.0-pro-exp-02-05', label: 'Gemini 2.0 Pro' },
                { value: 'gemini-1.5-pro-latest', label: 'Gemini 1.5 Pro' },
                { value: 'gemini-1.5-flash-latest', label: 'Gemini 1.5 Flash' }
            ];
        } else if (provider === 'anthropic') {
            options = [
                { value: 'claude-3-5-sonnet-20241022', label: 'Claude 3.5 Sonnet' },
                { value: 'claude-sonnet-4-6', label: 'Claude 4.6 Sonnet' },
                { value: 'claude-3-opus-20240229', label: 'Claude 3 Opus' },
                { value: 'claude-3-haiku-20240307', label: 'Claude 3 Haiku' }
            ];
        } else if (provider === 'ollama') {
            options = [
                { value: 'llama3', label: 'Llama 3' },
                { value: 'mistral', label: 'Mistral' },
                { value: 'gemma', label: 'Gemma' }
            ];
        }

        options.forEach(opt => {
            const option = document.createElement('option');
            option.value = opt.value;
            option.textContent = opt.label;
            if (opt.value === currentModel) option.selected = true;
            modelSelect.appendChild(option);
        });

        // Ensure the current model is selected if it matches
        if (currentModel && !options.find(o => o.value === currentModel)) {
            // If current model isn't in list, add it as a custom option
            const option = document.createElement('option');
            option.value = currentModel;
            option.textContent = currentModel + ' (Custom)';
            option.selected = true;
            modelSelect.appendChild(option);
        }

        if (modelSelect.options.length === 0) {
            console.warn("Model select is still empty after update!");
            const option = document.createElement('option');
            option.value = "";
            option.textContent = "No models available";
            modelSelect.appendChild(option);
        }
    }

    // Load history
    async function loadHistory() {
        try {
            const res = await fetch('/api/history?t=' + Date.now());
            if (!res.ok) return;
            const data = await res.json();
            chatHistory.innerHTML = ''; // Clear initial message
            data.history.forEach(msg => appendMessage(msg.role, msg.content, false));
            scrollToBottom();
        } catch (err) {
            console.error('Failed to load history', err);
        }
    }
    loadHistory();

    // Attachments
    // Microphone / Speech-to-Text
    const micBtn = document.getElementById('mic-btn');
    let recognition = null;

    if ('webkitSpeechRecognition' in window) {
        recognition = new webkitSpeechRecognition();
        recognition.continuous = false;
        recognition.interimResults = false;
        recognition.lang = 'en-US';

        recognition.onstart = function () {
            console.log("Mic recording started");
            micBtn.classList.add('recording');
            micBtn.style.color = '#ef4444'; // Red
            micBtn.style.borderColor = '#ef4444';
            userInput.placeholder = "Listening...";
        };

        recognition.onend = function () {
            console.log("Mic recording ended");
            micBtn.classList.remove('recording');
            micBtn.style.color = '';
            micBtn.style.borderColor = '';
            userInput.placeholder = "Type a message...";
        };

        recognition.onresult = function (event) {
            const transcript = event.results[0][0].transcript;
            console.log("Mic result:", transcript);
            userInput.value = transcript;
            // Auto-send for smoother experience
            sendMessage();
        };


        micBtn.addEventListener('click', () => {
            if (micBtn.classList.contains('recording')) {
                recognition.stop();
            } else {
                recognition.start();
            }
        });
    } else {
        console.warn("Web Speech API not supported");
        if (micBtn) {
            micBtn.style.display = 'none';
        }
    }

    const screenshotBtn = document.getElementById('screenshot-btn');
    if (screenshotBtn) {
        screenshotBtn.addEventListener('click', async () => {
            screenshotBtn.disabled = true;
            screenshotBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i>'; // Loading state

            try {
                const res = await fetch('/api/screenshot');
                const data = await res.json();

                if (data.image) {
                    // Add to pending images
                    pendingImages.push({
                        file: null, // No file object
                        base64: data.image,
                        isImage: true,
                        name: 'Screen Context.png'
                    });
                    renderPreviews();

                    userInput.value = "Take a look at my screen context and tell me what you see.";
                    sendMessage();
                }
            } catch (e) {
                console.error("Screenshot failed:", e);
                alert("Failed to capture screen context.");
            } finally {
                screenshotBtn.disabled = false;
                screenshotBtn.innerHTML = '<i class="fa-solid fa-eye"></i>';
            }
        });
    }

    attachBtn.addEventListener('click', () => imageInput.click());

    imageInput.addEventListener('change', async (e) => {
        const files = Array.from(e.target.files);
        for (const file of files) {
            const base64 = await fileToBase64(file);
            pendingImages.push({
                file,
                base64,
                isImage: file.type.startsWith('image/'),
                name: file.name
            });
        }
        renderPreviews();
        imageInput.value = ''; // Reset for next selection
    });

    function fileToBase64(file) {
        return new Promise((resolve, reject) => {
            const reader = new FileReader();
            reader.onload = () => resolve(reader.result);
            reader.onerror = reject;
            reader.readAsDataURL(file);
        });
    }

    function renderPreviews() {
        if (pendingImages.length === 0) {
            imagePreviewContainer.classList.add('hidden');
            return;
        }
        imagePreviewContainer.classList.remove('hidden');
        imagePreviewContainer.innerHTML = '';
        pendingImages.forEach((img, index) => {
            const div = document.createElement('div');
            div.className = 'preview-item';

            if (img.isImage) {
                div.innerHTML = `
                    <img src="${img.base64}" class="preview-thumb">
                    <button class="remove-img" data-index="${index}">&times;</button>
                `;
            } else {
                div.innerHTML = `
                    <div class="preview-thumb file-icon">
                        <i class="fa-solid fa-file"></i>
                        <span class="file-name-tag">${img.name}</span>
                    </div>
                    <button class="remove-img" data-index="${index}">&times;</button>
                `;
            }

            div.querySelector('.remove-img').onclick = (e) => {
                e.stopPropagation();
                pendingImages.splice(index, 1);
                renderPreviews();
            };
            imagePreviewContainer.appendChild(div);
        });
    }

    // Send Message
    async function sendMessage() {
        const text = userInput.value.trim();
        console.log("sendMessage triggered. Text length:", text.length, "isProcessing:", isProcessing);
        if (!text || isProcessing) return;

        // Stop current speech
        synth.cancel();

        userInput.value = '';
        userInput.style.height = 'auto';
        isProcessing = true;
        if (sendBtn) sendBtn.disabled = true;

        // Add user message
        let fullMessage = text;
        const nonImages = pendingImages.filter(img => !img.isImage);
        if (nonImages.length > 0) {
            fullMessage += "\n\n[Attached Files: " + nonImages.map(img => img.name).join(", ") + "]";
        }

        appendMessage('user', text, true, pendingImages.filter(img => img.isImage).map(img => img.base64));

        const imagesToSend = pendingImages.filter(img => img.isImage).map(img => img.base64);
        pendingImages = [];
        renderPreviews();

        // Create container for agent response
        const agentMsgDiv = appendMessage('agent', '');
        const contentDiv = agentMsgDiv.querySelector('.content');

        const statusDiv = document.createElement('div');
        statusDiv.className = 'agent-status';
        statusDiv.style.fontSize = '0.8rem';
        statusDiv.style.color = '#888';
        statusDiv.style.marginBottom = '5px';
        statusDiv.innerHTML = `<span class="thinking-pulse">📡</span> Connecting...`;
        contentDiv.prepend(statusDiv);

        const textDiv = document.createElement('div');
        contentDiv.appendChild(textDiv);

        let buffer = '';

        try {
            const response = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    message: fullMessage,
                    images: imagesToSend.length > 0 ? imagesToSend : null
                })
            });

            if (!response.ok) {
                if (response.status === 401) throw new Error('Unauthorized');
                throw new Error('Network response was not ok');
            }

            const reader = response.body.getReader();
            const decoder = new TextDecoder();

            while (true) {
                const { done, value } = await reader.read();
                if (done) break;

                buffer += decoder.decode(value, { stream: true });
                const lines = buffer.split('\n');

                buffer = lines.pop();

                for (const line of lines) {
                    if (!line.trim()) continue;
                    try {
                        const event = JSON.parse(line);
                        handleEvent(event, statusDiv, textDiv);
                    } catch (e) {
                        console.error("JSON parse error:", e, line);
                    }
                }
                scrollToBottom();
            }

        } catch (err) {
            textDiv.innerHTML += `<br>**Error:** ${err.message}`;
        } finally {
            isProcessing = false;
            sendBtn.disabled = false;
            statusDiv.textContent = '';
            userInput.focus();
        }
    }

    // Safe Markdown Parsing
    function safeMarked(content) {
        if (typeof marked === 'undefined') return content;
        try {
            return marked.parse(content);
        } catch (e) {
            console.error("Marked error:", e);
            return content;
        }
    }

    // Configure Marked if available
    if (typeof marked !== 'undefined' && typeof hljs !== 'undefined') {
        try {
            marked.setOptions({
                highlight: function (code, lang) {
                    const language = hljs.getLanguage(lang) ? lang : 'plaintext';
                    return hljs.highlight(code, { language }).value;
                },
                langPrefix: 'hljs language-'
            });
        } catch (e) {
            console.warn("Could not set marked options", e);
        }
    }

    function handleEvent(event, statusDiv, textDiv) {
        console.log("Received event:", event.type, event);
        if (event.type === 'thinking') {
            statusDiv.innerHTML = `<span class="thinking-pulse">🧠</span> ${event.content}`;
        }
        else if (event.type === 'error') {
            console.error("Backend Error:", event.content);
            statusDiv.innerHTML = `<span style="color: #ff4d4d">❌ Error</span>`;
            const errorBlock = document.createElement('div');
            errorBlock.className = 'message system';
            errorBlock.style.color = '#ff4d4d';

            let html = `<strong>Error:</strong> ${event.content}`;

            // Helpful suggestion
            if (event.content.includes("AI Provider Error")) {
                html += `<div style="margin-top: 10px; font-size: 0.9em; opacity: 0.9; background: rgba(255, 77, 77, 0.1); padding: 8px; border-radius: 6px;">
                    <strong>💡 Suggestion:</strong> Try switching to a different <strong>LLM Provider</strong> (like OpenAI) or a different <strong>Model</strong> in the sidebar.
                </div>`;
            }

            errorBlock.innerHTML = html;
            textDiv.appendChild(errorBlock);
        }
        else if (event.type === 'tool_start') {
            console.log("Tool Started:", event.tool);
            const toolCard = document.createElement('div');
            toolCard.className = 'tool-card running';

            let icon = '🔧';
            if (event.tool.includes('search') || event.tool.includes('browse')) icon = '🔍';
            if (event.tool.includes('canvas')) icon = '🎨';

            toolCard.innerHTML = `
                <div class="tool-header"><span class="thinking-pulse">${icon}</span> Running: <code>${event.tool}</code></div>
                <div class="tool-args">${event.args}</div>
            `;
            textDiv.appendChild(toolCard);

            // Also update the main status div at the top
            statusDiv.innerHTML = `<span class="thinking-pulse">${icon}</span> Running ${event.tool}...`;

            // Canvas Integration for Active Search / Video
            if (event.tool.includes('search') || event.tool.includes('browse') || event.tool.includes('watch_video')) {
                toggleCanvas(true);
                const isVideo = event.tool.includes('watch_video');
                canvasContent.innerHTML = `
                    <div class="canvas-card" id="scanning-animation" style="text-align: center; padding: 40px;">
                        <h4 style="margin-bottom: 20px;">${isVideo ? 'Processing Video...' : 'Scanning Web...'}</h4>
                        <div class="thinking-pulse" style="font-size: 3rem;">${isVideo ? '🎬' : '🔍'}</div>
                        <p style="color: #666; margin-top: 20px;">${isVideo ? 'Downloading and analyzing frames for:' : 'Searching for:'} <br><code>${event.args}</code></p>
                    </div>
                `;

                // Safety timeout: if no result comes back in 45s, show error on canvas
                setTimeout(() => {
                    const scanningEl = document.getElementById('scanning-animation');
                    if (scanningEl) {
                        console.warn("Frontend Timeout: No result received in 45s for tool", event.tool);
                        scanningEl.innerHTML = `
                            <h4 style="margin-bottom: 20px; color: #f59e0b;">Search Timed Out</h4>
                            <div style="font-size: 3rem;">⚠️</div>
                            <p style="color: #666; margin-top: 20px;">The search tool took too long to respond.</p>
                         `;
                    }
                }, 45000);
            }
        }
        else if (event.type === 'tool_end') {
            console.log("Tool Ended");
            const cards = textDiv.querySelectorAll('.tool-card.running');
            if (cards.length > 0) {
                const card = cards[cards.length - 1];
                card.classList.remove('running');
                card.classList.add('finished');
                const outputDiv = document.createElement('div');
                outputDiv.className = 'tool-output';

                // Robustly handle string or array output
                let outputPreview = "";
                if (Array.isArray(event.output)) {
                    outputPreview = event.output[0];
                } else if (typeof event.output === 'string') {
                    outputPreview = event.output;
                }

                if (outputPreview.length > 100) {
                    outputPreview = outputPreview.substring(0, 100) + '...';
                }

                outputDiv.innerText = `Result: ${outputPreview}`;
                card.appendChild(outputDiv);
            }

            // Safety: If scanning animation is still on canvas, it means canvas_update failed or wasn't sent.
            // Replace it with the raw output so the user isn't stuck waiting.
            const scanningEl = document.getElementById('scanning-animation');
            if (scanningEl) {
                console.warn("Tool ended but scanning animation persists. Clearing it.");
                // Use the output as fallback content
                renderCanvasContent({
                    type: 'ocr',
                    text: `Search finished. Raw Output:\n\n${event.output}`
                });
            }
        }
        else if (event.type === 'canvas_update') {
            console.log("Canvas Update received");
            toggleCanvas(true);
            renderCanvasContent(event.content);
        }
        else if (event.type === 'content') {
            // Append a new markdown-rendered block
            const newBlock = document.createElement('div');
            newBlock.className = 'markdown-block';
            newBlock.innerHTML = safeMarked(event.content);
            textDiv.appendChild(newBlock);

            // Voice
            speak(event.content);
        }
    }

    function renderCanvasContent(content) {
        if (!content) return;

        if (typeof content === 'string') {
            const trimmed = content.trim();
            if (trimmed.startsWith('<')) {
                canvasContent.innerHTML = content;
            } else {
                try {
                    const data = JSON.parse(content);
                    renderVisualData(data);
                } catch (e) {
                    canvasContent.innerHTML = `<div class="canvas-card"><h4>Result</h4><div class="ocr-result">${content}</div></div>`;
                }
            }
        } else {
            renderVisualData(content);
        }
    }

    function renderVisualData(data) {
        if (data.type === 'color_palette') {
            let html = `
                <div class="canvas-card">
                    <h4><i class="fa-solid fa-palette"></i> Extracted Color Palette</h4>
                    <div class="color-palette">
            `;
            data.colors.forEach(clr => {
                html += `
                    <div class="color-swatch">
                        <div class="swatch-box" style="background: ${clr.hex}" title="Click to copy" onclick="navigator.clipboard.writeText('${clr.hex}')"></div>
                        <div class="swatch-info">
                            <div class="swatch-label">Hex</div>
                            <div class="swatch-value">${clr.hex}</div>
                            <div class="swatch-label">RGB</div>
                            <div class="swatch-value">${clr.rgb}</div>
                            ${clr.pigment ? `<div class="pigment-info">${clr.pigment}</div>` : ''}
                        </div>
                    </div>
                `;
            });
            html += `</div></div>`;
            canvasContent.innerHTML = html;
        } else if (data.type === 'ocr') {
            canvasContent.innerHTML = `
                <div class="canvas-card">
                    <h4><i class="fa-solid fa-file-lines"></i> OCR Text Extraction</h4>
                    <div class="ocr-result">${data.text}</div>
                </div>
            `;
        } else if (data.type === 'search_results') {
            let html = `<div class="canvas-card"><h4><i class="fa-solid fa-globe"></i> Search Results</h4>`;
            data.results.forEach(res => {
                html += `
                    <div style="margin-bottom: 15px; padding-bottom: 15px; border-bottom: 1px solid #eee;">
                        <a href="${res.url}" target="_blank" style="font-weight: bold; color: #2563eb; text-decoration: none; display: block; margin-bottom: 4px;">${res.title}</a>
                        <div style="font-size: 0.8rem; color: #22c55e; margin-bottom: 4px;">${res.url}</div>
                        <div style="font-size: 0.9rem; color: #4b5563;">${res.snippet}</div>
                    </div>
                `;
            });
            html += `</div>`;
            canvasContent.innerHTML = html;
        } else if (data.type === 'web_preview') {
            // FULL-PAGE WEB PREVIEW
            canvasContent.innerHTML = `
                <div class="canvas-card" style="padding: 0; background: #fff; border-color: #e5e7eb; overflow: hidden; height: calc(100% - 20px);">
                    <div style="background: #f3f4f6; padding: 10px 20px; border-bottom: 1px solid #e5e7eb; display: flex; align-items: center; justify-content: space-between;">
                        <div style="font-size: 0.85rem; font-weight: 600; color: #374151;"><i class="fa-solid fa-display"></i> ${data.title || 'Web Preview'}</div>
                        <div style="display: flex; gap: 4px;">
                            <button onclick="const blob = new Blob([this.closest('.canvas-card').querySelector('iframe').srcdoc], {type: 'text/html'}); const a = document.createElement('a'); a.href = URL.createObjectURL(blob); a.download = '${data.title || 'web_project'}.html'; a.click();" class="icon-btn" title="Download HTML" style="height: 24px; width: 24px; padding: 0;">
                                <i class="fa-solid fa-download" style="font-size: 0.8rem;"></i>
                            </button>
                            <div style="width: 10px; height: 10px; background: #fbbf24; border-radius: 50%;"></div>
                            <div style="width: 10px; height: 10px; background: #f87171; border-radius: 50%;"></div>
                        </div>
                    </div>
                    <iframe id="web-preview-frame" style="width: 100%; height: calc(100% - 41px); border: none; background: white;"></iframe>
                </div>
            `;
            const frame = document.getElementById('web-preview-frame');
            frame.srcdoc = data.html;
        } else if (data.type === 'monitor_stream') {
            // LIVE MONITOR STREAM
            // We want to replace the image src efficiently if it already exists to avoid flicker
            const existingStream = document.getElementById('monitor-stream-img');
            const goalEl = document.getElementById('hud-goal');
            const toolEl = document.getElementById('hud-tool');
            const ctxEl = document.getElementById('hud-context');

            if (existingStream) {
                existingStream.src = data.image;
                if (data.goal && goalEl) goalEl.textContent = data.goal;
                if (data.tool && toolEl) toolEl.textContent = data.tool;
                if (data.context && ctxEl) ctxEl.textContent = data.context;
            } else {
                canvasContent.innerHTML = `
                    <div class="canvas-card" style="padding: 0; background: #000; overflow: hidden; height: 100%; display: flex; flex-direction: column;">
                        <div style="padding: 10px; background: #1f2937; color: #fff; display: flex; justify-content: space-between; align-items: center;">
                            <div style="font-weight: 600;"><i class="fa-solid fa-video"></i> Ruby Vision</div>
                            <div style="font-size: 0.8rem; color: #ef4444; display: flex; align-items: center; gap: 6px;">
                                <i class="fa-solid fa-circle fa-beat" style="font-size: 8px;"></i> LIVE
                            </div>
                        </div>
                        
                        <!-- HUD Overlay (Top) -->
                        <div style="background: rgba(31, 41, 55, 0.9); padding: 10px; border-bottom: 1px solid #374151; font-size: 0.85rem;">
                            <div style="display: flex; margin-bottom: 4px;">
                                <span style="color: #4ade80; width: 60px; font-weight: bold;">GOAL:</span>
                                <span id="hud-goal" style="color: #fff;">${data.goal || 'Standing By'}</span>
                            </div>
                            <div style="display: flex; margin-bottom: 4px;">
                                <span style="color: #60a5fa; width: 60px; font-weight: bold;">TOOL:</span>
                                <span id="hud-tool" style="color: #fff;">${data.tool || 'Idle'}</span>
                            </div>
                            <div style="display: flex;">
                                <span style="color: #c084fc; width: 60px; font-weight: bold;">CTX:</span>
                                <span id="hud-context" style="color: #d1d5db;">${data.context || '...'}</span>
                            </div>
                        </div>

                        <div style="flex: 1; position: relative; display: flex; align-items: center; justify-content: center; background: #000; overflow: hidden;">
                            <img id="monitor-stream-img" src="${data.image}" style="max-width: 100%; max-height: 100%; object-fit: contain;">
                        </div>
                    </div>
                `;
            }
        } else if (data.type === 'search_error') {
            // SEARCH ERROR
            canvasContent.innerHTML = `
                <div class="canvas-card">
                    <h4 style="color: #ef4444;"><i class="fa-solid fa-triangle-exclamation"></i> Search Failed</h4>
                    <div style="padding: 20px; text-align: center;">
                        <div style="font-size: 3rem; margin-bottom: 20px;">⚠️</div>
                        <p style="color: #374151; font-weight: bold; margin-bottom: 10px;">${data.error || 'Unknown Error'}</p>
                        <p style="color: #6b7280; font-size: 0.9rem;">
                            Query: <code>${data.query || 'N/A'}</code>
                        </p>
                        <button onclick="toggleCanvas(false)" class="btn btn-secondary" style="margin-top: 20px;">Close</button>
                    </div>
                </div>
            `;
        } else if (data.type === 'pin_preview') {
            // PINTEREST PIN PREVIEW (2:3 Aspect Ratio)
            canvasContent.innerHTML = `
                <div class="canvas-card" style="max-width: 400px; margin: 0 auto; padding: 0; background: #fff; border-radius: 16px; overflow: hidden; box-shadow: 0 10px 25px rgba(0,0,0,0.15);">
                    <div style="position: relative; width: 100%; padding-top: 150%;"> <!-- 2:3 aspect ratio -->
                        <img src="${data.url}" style="position: absolute; top: 0; left: 0; width: 100%; height: 100%; object-fit: cover;">
                    </div>
                </div>
            `;
        } else if (data.type === 'monitor_stream') {
            // LIVE MONITOR STREAM
            // We want to replace the image src efficiently if it already exists to avoid flicker
            const existingStream = document.getElementById('monitor-stream-img');
            if (existingStream) {
                existingStream.src = data.image;
                // Update HUD text if present in data (though it's baked into image now)
            } else {
                canvasContent.innerHTML = `
                    <div class="canvas-card" style="padding: 0; background: #000; overflow: hidden; height: 100%; display: flex; flex-direction: column;">
                        <div style="padding: 10px; background: #1f2937; color: #fff; display: flex; justify-content: space-between; align-items: center;">
                            <div style="font-weight: 600;"><i class="fa-solid fa-video"></i> Ruby Vision</div>
                            <div style="font-size: 0.8rem; color: #ef4444;"><i class="fa-solid fa-circle fa-beat"></i> LIVE</div>
                        </div>
                        <div style="flex: 1; position: relative; display: flex; align-items: center; justify-content: center; background: #000;">
                            <img id="monitor-stream-img" src="${data.image}" style="max-width: 100%; max-height: 100%; object-fit: contain;">
                        </div>
                    </div>
                `;
            }
        }
        else if (data.title && data.body) {
            // GENERIC CONTENT HANDLER (Markdown/HTML)
            const bodyContent = data.body.trim().startsWith('<') ? data.body : safeMarked(data.body);
            const btnId = 'copy-cnv-' + Date.now();

            canvasContent.innerHTML = `
                <div class="canvas-card">
                    <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 16px; border-bottom: 1px solid rgba(255,255,255,0.1); padding-bottom: 8px;">
                        <h4 style="margin: 0; border: none; padding-top: 4px;">${data.title}</h4>
                <div style="display: flex; gap: 8px;">
                            <button id="dl-${btnId}" class="icon-btn" title="Download" style="height: 32px; width: 32px;">
                                <i class="fa-solid fa-download"></i>
                            </button>
                            <button id="${btnId}" class="icon-btn" title="Copy content" style="height: 32px; width: 32px;">
                                <i class="fa-regular fa-copy"></i>
                            </button>
                        </div>
                    </div>
                    <div class="markdown-body">${bodyContent}</div>
                </div>
            `;

            // Attach listeners securely via closure
            setTimeout(() => {
                const btn = document.getElementById(btnId);
                const dlBtn = document.getElementById(`dl-${btnId}`);

                if (dlBtn) {
                    dlBtn.onclick = () => {
                        const blob = new Blob([data.body], { type: 'text/plain' });
                        const url = window.URL.createObjectURL(blob);
                        const a = document.createElement('a');
                        a.style.display = 'none';
                        a.href = url;
                        // Guess extension
                        let ext = '.txt';
                        if (data.body.trim().startsWith('<')) ext = '.html';
                        if (data.title && data.title.toLowerCase().includes('script')) ext = '.py';
                        if (data.title && data.title.toLowerCase().includes('json')) ext = '.json';

                        a.download = (data.title || 'download').replace(/[^a-z0-9]/gi, '_') + ext;
                        document.body.appendChild(a);
                        a.click();
                        window.URL.revokeObjectURL(url);
                        document.body.removeChild(a);
                    };
                }

                if (btn) {
                    btn.onclick = async () => {
                        try {
                            const card = btn.closest('.canvas-card');
                            const markdownBody = card.querySelector('.markdown-body');

                            if (markdownBody) {
                                const html = markdownBody.innerHTML;
                                const text = markdownBody.innerText; // Get visible text (no markdown syntax)

                                const blobHtml = new Blob([html], { type: 'text/html' });
                                const blobText = new Blob([text], { type: 'text/plain' });

                                await navigator.clipboard.write([
                                    new ClipboardItem({
                                        'text/html': blobHtml,
                                        'text/plain': blobText
                                    })
                                ]);
                            } else {
                                // Fallback if element not found (unlikely)
                                await navigator.clipboard.writeText(data.body);
                            }

                            const icon = btn.querySelector('i');
                            const originalClass = icon.className;
                            icon.className = 'fa-solid fa-check';
                            icon.style.color = '#4ade80'; // Green
                            setTimeout(() => {
                                icon.className = originalClass;
                                icon.style.color = '';
                            }, 2000);
                        } catch (err) {
                            console.error('Failed to copy to clipboard:', err);
                            // Fallback to simple text copy if rich copy fails
                            try {
                                navigator.clipboard.writeText(data.body);
                                alert('Rich copy failed, copied raw markdown instead.');
                            } catch (e) {
                                alert('Failed to copy to clipboard');
                            }
                        }
                    };
                }
            }, 0);

        } else {
            canvasContent.innerHTML = `<div class="canvas-card"><h4>Data Result</h4><pre class="ocr-result">${JSON.stringify(data, null, 2)}</pre></div>`;
        }
    }

    // Linkify URLs in text
    function linkify(text) {
        if (!text) return "";
        // Escape HTML for safety
        const div = document.createElement('div');
        div.textContent = text;
        const escaped = div.innerHTML;

        // Regex for URLs (http, https, www)
        const urlRegex = /(((https?:\/\/)|(www\.))[^\s]+)/g;
        return escaped.replace(urlRegex, function (url) {
            let href = url;
            if (url.startsWith('www.')) {
                href = 'http://' + url;
            }
            return `<a href="${href}" target="_blank" class="chat-link">${url}</a>`;
        });
    }

    // Append Message to UI
    function appendMessage(role, content, animate = true, images = null) {
        // Unify agent/assistant roles for consistent rendering and styling
        const isAgent = (role === 'agent' || role === 'assistant');
        const displayRole = isAgent ? 'agent' : role;

        const msgDiv = document.createElement('div');
        msgDiv.className = `message ${displayRole}`;
        if (animate) msgDiv.style.animation = 'fadeIn 0.3s ease';

        const contentDiv = document.createElement('div');
        contentDiv.className = 'content';

        // Add Copy Button for Agent messages
        if (isAgent) {
            const copyBtn = document.createElement('button');
            copyBtn.className = 'copy-msg-btn';
            copyBtn.innerHTML = '<i class="fa-solid fa-copy"></i>';
            copyBtn.title = 'Copy to clipboard';
            copyBtn.onclick = (e) => {
                e.stopPropagation(); // Avoid triggering any voice/click event
                navigator.clipboard.writeText(content).then(() => {
                    const icon = copyBtn.querySelector('i');
                    icon.className = 'fa-solid fa-check';
                    icon.style.color = '#4ade80';
                    setTimeout(() => {
                        icon.className = 'fa-solid fa-copy';
                        icon.style.color = '';
                    }, 2000);
                });
            };
            msgDiv.appendChild(copyBtn);
        }

        // Images
        if (images && images.length > 0) {
            images.forEach(imgData => {
                const img = document.createElement('img');
                img.src = imgData;
                img.className = 'message-image';
                img.onclick = () => window.open(imgData, '_blank');
                contentDiv.appendChild(img);
            });
        }

        // Text
        const textWrapper = document.createElement('div');
        textWrapper.className = 'text-wrapper';

        // Apply markdown-body class to agent messages for styling
        if (isAgent) {
            contentDiv.classList.add('markdown-body');
            if (content) {
                textWrapper.innerHTML = safeMarked(content);
            } else {
                textWrapper.innerHTML = '<span class="typing-indicator">...</span>';
            }
        } else if (role === 'user') {
            textWrapper.innerHTML = linkify(content); // Support clickable URLs in user messages
        } else {
            textWrapper.textContent = content; // System messages, etc.
        }

        contentDiv.appendChild(textWrapper);
        msgDiv.appendChild(contentDiv);
        chatHistory.appendChild(msgDiv);
        scrollToBottom();
        return msgDiv;
    }

    // Update message content (with Markdown parsing)
    function updateMessageContent(element, text) {
        if (!text) {
            element.innerHTML = '<span class="typing-indicator">...</span>';
            return;
        }
        // Use safeMarked to render markdown
        element.innerHTML = safeMarked(text);
    }

    function scrollToBottom() {
        chatHistory.scrollTop = chatHistory.scrollHeight;
    }

    // Consolidated Send Logic (Supports Mouse & Keyboard)
    sendBtn.addEventListener('click', () => {
        console.log("Send button clicked");
        sendMessage();
    });

    userInput.addEventListener('keydown', (e) => {
        const isEnter = e.key === 'Enter' || e.code === 'Enter' || e.code === 'NumpadEnter' || e.keyCode === 13;

        if (isEnter && !e.shiftKey) {
            e.preventDefault();
            console.log("Enter key detected:", e.key, e.code, e.keyCode);
            sendMessage();
        }
    });

    // Global focus helper: ensure the input is focused when clicking on the chat area background
    document.addEventListener('click', (e) => {
        // Only auto-focus if we click the background areas, not on interactive elements or messages
        const isBackground = e.target.classList.contains('chat-history') ||
            e.target.id === 'main-app' ||
            e.target.tagName === 'MAIN';

        if (isBackground && window.getSelection().toString() === '') {
            console.log("Auto-focusing user input from background click");
            userInput.focus();
        }
    });

    // Ensure input is always enabled and has focus on start
    if (userInput) {
        userInput.disabled = false;
        userInput.focus();
    }

    // Handle "Clear" button separately to avoid any focus issues
    if (clearBtn) {
        clearBtn.onclick = async () => {
            console.log("Clear History button clicked");
            if (confirm('Are you sure you want to clear your conversation history? This cannot be undone.')) {
                try {
                    const res = await fetch('/api/reset', { method: 'POST' });
                    if (res.ok) {
                        chatHistory.innerHTML = '<div class="message system"><div class="content">History cleared.</div></div>';
                        appendMessage('system', 'You can now start a new conversation.');
                        scrollToBottom();
                        console.log("History cleared successfully");
                    } else {
                        throw new Error('Failed to reset history on server');
                    }
                } catch (err) {
                    console.error('Clear history error:', err);
                    alert('Failed to clear history. Please try restarting the application.');
                }
            }
        };
    }

    // Handle "View Memory" button
    const viewMemoryBtn = document.getElementById('view-memory-btn');
    if (viewMemoryBtn) {
        viewMemoryBtn.addEventListener('click', () => {
            userInput.value = "What do you know about me? Show me my current focus and preferences from your memory.";
            sendMessage();
        });
    }

    providerSelect.addEventListener('change', async (e) => {
        const provider = e.target.value;
        updateModelOptions(provider, providerModels[provider]?.[0]);
        const model = modelSelect.value;

        try {
            const res = await fetch('/api/switch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, model })
            });
            const data = await res.json();
            if (data.status === 'success') {
                currentModelDisplay.textContent = data.model;
                appendMessage('system', `Switched to ${data.provider} (${data.model})`);
            }
        } catch (err) {
            console.error('Failed to switch provider', err);
            alert('Failed to switch provider. Check logs.');
        }
    });

    modelSelect.addEventListener('change', async (e) => {
        const provider = providerSelect.value;
        const model = e.target.value;

        try {
            const res = await fetch('/api/switch', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ provider, model })
            });
            const data = await res.json();
            if (data.status === 'success') {
                currentModelDisplay.textContent = data.model;
                appendMessage('system', `Model updated to ${data.model}`);
            }
        } catch (err) {
            console.error('Failed to update model', err);
        }
    });

    hybridRoutingCheck.addEventListener('change', async (e) => {
        const enabled = e.target.checked;
        try {
            await fetch('/api/config', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ hybrid_routing: enabled })
            });
            appendMessage('system', `Hybrid Routing ${enabled ? 'Enabled' : 'Disabled'} (FunctionGemma will ${enabled ? 'now' : 'no longer'} route local tools)`);
        } catch (err) {
            console.error('Failed to update hybrid routing', err);
        }
    });

    voiceToggle.addEventListener('change', (e) => {
        isVoiceEnabled = e.target.checked;
        if (isVoiceEnabled) {
            // Browsers often need interaction to initialize speech engines
            populateVoiceList();

            const selectedVoiceIndex = voiceSelect.value;
            const voiceName = voices[selectedVoiceIndex] ? voices[selectedVoiceIndex].name : "Default";
            appendMessage('system', `Voice Enabled (Using: ${voiceName})`);

            speak("Voice enabled.");
        } else {
            synth.cancel();
            appendMessage('system', `Voice Disabled`);
        }
    });

    if (refreshVoicesBtn) {
        refreshVoicesBtn.addEventListener('click', () => {
            if (populateVoiceList()) {
                appendMessage('system', "Voice list refreshed.");
            } else {
                appendMessage('system', "No voices found. Check browser permissions.");
            }
        });
    }

    // Real-time Event Listener (SSE)
    const eventSource = new EventSource('/api/events');
    eventSource.onmessage = (event) => {
        const data = JSON.parse(event.data);
        console.log("Real-time Event:", data);
        // We can use this to show background thinking or status updates
    };
});
