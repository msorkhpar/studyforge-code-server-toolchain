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

/** The ways into the chat: Quick Chat, the toggle, the panel's own id and the view.
 *  ⚠️ In this order, measured. The secondary side bar starts HIDDEN (the
 *  Dockerfile step "THE SECONDARY SIDE BAR NEVER OPENS"), and with the view
 *  asked for first, the toggle and the panel's id after it closed that bar
 *  again, so the plant left only Quick Chat on screen and no chat view. The
 *  view is asked for LAST so a plant is left looking at it. */
const OPENERS = [
    'workbench.action.openQuickChat',
    'workbench.action.chat.toggle',
    'workbench.panel.chat',
    'workbench.action.chat.open',
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
