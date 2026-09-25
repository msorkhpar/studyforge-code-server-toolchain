/*
 * A TEST FIXTURE, installed only into a derived image by tests/test_editor_no_ai.py.
 *
 * It reads the workbench's own command registry -- `getCommands` answers from
 * the workbench, not from this extension host -- and then asks for the chat
 * the way a menu or a keybinding would, with `executeCommand`. It also reads
 * the AI switch's default, which the workbench's configuration registry hands
 * every extension host. All of it lands in `commands.json` in the log directory
 * the workbench gives it, for the test to read with `docker exec`.
 *
 * ⚠️ It waits until the lockdown's last close has run (its retries end at
 * 12 s), so a chat view it opens is one the reader would be left looking at.
 */
const vscode = require('vscode');
const fs = require('fs');
const path = require('path');

/** The ways into the chat: the view, the panel's own id, its toggle and Quick Chat.
 *  ⚠️ In this order, measured: with the toggle first, the plant left no view open. */
const OPENERS = [
    'workbench.action.chat.open',
    'workbench.panel.chat',
    'workbench.action.chat.toggle',
    'workbench.action.openQuickChat',
];
const AFTER_THE_LOCKDOWN = 20000;

exports.activate = function (context) {
    const out = context.logUri.fsPath;
    fs.mkdirSync(out, { recursive: true });
    setTimeout(async function () {
        const commands = (await vscode.commands.getCommands(false)).sort();
        const opened = {};
        for (const id of OPENERS) {
            try {
                await vscode.commands.executeCommand(id);
                opened[id] = 'ran';
            } catch (error) {
                opened[id] = String((error && error.message) || error).slice(0, 200);
            }
        }
        const inspected = vscode.workspace.getConfiguration('chat').inspect('disableAIFeatures') || {};
        const aiSwitch = { defaultValue: inspected.defaultValue, globalValue: inspected.globalValue };
        const partial = path.join(out, 'commands.partial');
        fs.writeFileSync(partial, JSON.stringify({ commands, opened, aiSwitch }));
        fs.renameSync(partial, path.join(out, 'commands.json'));
    }, AFTER_THE_LOCKDOWN);
};

exports.deactivate = function () {};
