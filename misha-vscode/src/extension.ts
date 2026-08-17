import * as vscode from 'vscode';
import * as http from 'http';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

const MISHA_PORT = 47384;
const SESSION_FILE = path.join(os.homedir(), '.misha', 'ide', 'session.json');

type MishaSession = { token: string; port: number };

function readSession(): MishaSession | undefined {
    try {
        const parsed = JSON.parse(fs.readFileSync(SESSION_FILE, 'utf8'));
        if (typeof parsed.token !== 'string' || parsed.token.length < 32) {
            return undefined;
        }
        const port = Number.isInteger(parsed.port) ? parsed.port : MISHA_PORT;
        return { token: parsed.token, port };
    } catch {
        return undefined;
    }
}

function sendContextToMisha() {
    const editor = vscode.window.activeTextEditor;
    if (!editor) {
        sendPayload({ file_path: '', language: '', cursor_line: 0, selection: '' });
        return;
    }

    const document = editor.document;
    const selection = editor.selection;
    const selectedText = document.getText(selection);

    const payload = {
        file_path: document.uri.fsPath,
        language: document.languageId,
        cursor_line: selection.active.line + 1,
        selection: selectedText
    };

    sendPayload(payload);
}

function sendPayload(data: any) {
    const session = readSession();
    if (!session) {
        return;
    }
    const postData = JSON.stringify(data);
    const options = {
        hostname: '127.0.0.1',
        port: session.port,
        path: '/',
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Content-Length': Buffer.byteLength(postData),
            'Authorization': `Bearer ${session.token}`
        }
    };

    const req = http.request(options, (res) => {
        // Silently ignore response to prevent spam
        res.on('data', () => {});
    });

    req.on('error', (e) => {
        // Silently ignore connection errors (e.g. when Misha is closed)
    });

    req.write(postData);
    req.end();
}

export function activate(context: vscode.ExtensionContext) {
    // Send initial context
    sendContextToMisha();

    // Listen to editor changes
    context.subscriptions.push(
        vscode.window.onDidChangeActiveTextEditor(() => {
            sendContextToMisha();
        }),
        vscode.window.onDidChangeTextEditorSelection(() => {
            sendContextToMisha();
        })
    );

    // Register manual command
    let disposable = vscode.commands.registerCommand('misha-ide-context.ping', () => {
        sendContextToMisha();
        vscode.window.showInformationMessage('Sent context to Misha!');
    });

    context.subscriptions.push(disposable);
}

export function deactivate() {}
