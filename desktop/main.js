const { app, BrowserWindow } = require('electron');
const path = require('path');
const { spawn } = require('child_process');

let mainWindow;
let pythonProcess;

const APP_ID = "com.ruby.assistant";
if (process.platform === 'win32') {
    app.setAppUserModelId(APP_ID);
}

function createWindow() {
    mainWindow = new BrowserWindow({
        width: 1200,
        height: 800,
        title: "Ruby Assistant",
        icon: path.join(__dirname, '../ruby_icon.ico'),
        webPreferences: {
            nodeIntegration: false,
            contextIsolation: true,
            preload: path.join(__dirname, 'preload.js')
        },
        autoHideMenuBar: true,
        backgroundColor: '#0f172a'
    });

    // Point to the FastAPI server (running on 8000)
    mainWindow.loadURL('http://localhost:8000');

    mainWindow.on('closed', function () {
        mainWindow = null;
    });
}

function startPythonBackend() {
    // Start the Python server (main.py)
    const scriptPath = path.join(__dirname, '../main.py');
    console.log(`Starting python backend: python ${scriptPath}`);

    // Check for venv python
    const venvPython = process.platform === 'win32'
        ? path.join(__dirname, '../venv/Scripts/python.exe')
        : path.join(__dirname, '../venv/bin/python');

    const pythonExec = require('fs').existsSync(venvPython) ? venvPython : 'python';
    console.log(`Using python executable: ${pythonExec}`);

    pythonProcess = spawn(pythonExec, [scriptPath], {
        cwd: path.join(__dirname, '..'),
        env: { ...process.env, PYTHONUNBUFFERED: '1' }
    });

    pythonProcess.on('error', (err) => {
        console.error('Failed to start python process:', err);
    });

    pythonProcess.stdout.on('data', (data) => {
        console.log(`Ruby Engine: ${data}`);
    });

    pythonProcess.stderr.on('data', (data) => {
        console.error(`Ruby Engine Error: ${data}`);
    });
}

app.on('ready', () => {
    startPythonBackend();

    // Give the backend a moment to start before showing the window
    setTimeout(createWindow, 2000);
});

app.on('window-all-closed', function () {
    if (process.platform !== 'darwin') {
        if (pythonProcess) pythonProcess.kill();
        app.quit();
    }
});

app.on('activate', function () {
    if (mainWindow === null) {
        createWindow();
    }
});

app.on('will-quit', () => {
    if (pythonProcess) pythonProcess.kill();
});

// Context Menu Implementation (Copy, Paste, Delete, Spellcheck)
const { Menu, MenuItem } = require('electron');

app.on('browser-window-created', (event, window) => {
    window.webContents.on('context-menu', (event, params) => {
        const menu = new Menu();

        // Add spelling suggestions
        for (const suggestion of params.dictionarySuggestions) {
            menu.append(new MenuItem({
                label: suggestion,
                click: () => window.webContents.replaceMisspelling(suggestion)
            }));
        }

        // Allow users to add to dictionary
        if (params.misspelledWord) {
            menu.append(new MenuItem({
                label: 'Add to Dictionary',
                click: () => window.webContents.session.addWordToSpellCheckerDictionary(params.misspelledWord)
            }));
            menu.append(new MenuItem({ type: 'separator' }));
        }

        // Standard actions
        menu.append(new MenuItem({ label: 'Cut', role: 'cut', enabled: params.editFlags.canCut }));
        menu.append(new MenuItem({ label: 'Copy', role: 'copy', enabled: params.editFlags.canCopy }));
        menu.append(new MenuItem({ label: 'Paste', role: 'paste', enabled: params.editFlags.canPaste }));
        menu.append(new MenuItem({ label: 'Delete', role: 'delete', enabled: params.editFlags.canDelete }));
        menu.append(new MenuItem({ type: 'separator' }));
        menu.append(new MenuItem({ label: 'Select All', role: 'selectAll', enabled: params.editFlags.canSelectAll }));

        menu.popup();
    });
});
