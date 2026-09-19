/*
 * One practice, and nothing else.
 *
 * A study page embeds this editor in an iframe beside the lesson, and the
 * reader's whole job in it is: read the test, edit the file, press Run on the
 * page. Everything else the workbench offers -- the explorer, the terminal,
 * the panel, tabs, other files -- is a way to end up somewhere the lesson did
 * not send them, so the layout is closed on startup and re-closed whenever the
 * practice changes.
 *
 * What this file does NOT do, on purpose:
 *
 *   - it is not a security boundary. code-server is an IDE with a shell, and
 *     an iframe of one is exactly as powerful as the process behind it. This
 *     removes the ways *in*, not the possibility. The security boundary is
 *     the container, the loopback bind and the one exact `--embed-origin`.
 *   - it does not make files read-only. That is `files.readonlyInclude` /
 *     `files.readonlyExclude` in the workspace settings the study server
 *     writes, which the editor enforces itself.
 *   - it does not open any file. A page shows a practice in TWO iframes of
 *     this one code-server -- the file to edit in one, the test that judges
 *     it in the other -- and which file a window shows is decided by that
 *     window's own URL, through code-server's
 *     `payload=[["openFile", "vscode-remote://<host:port><abs path>"]]`.
 *     Nothing else can tell the two windows apart: an extension cannot read
 *     its own window's query string, and both windows share one workspace
 *     settings file, so anything this extension opened it would open in both.
 *
 * Which leaves it one job, and no knowledge of the practice at all: close
 * everything around the editor, and close every editor but the active one.
 *
 * ⛔ This extension belongs to no consumer and names none. Its identifier and
 * the configuration section below are this framework's, and both are derived
 * from ONE place -- `package.json` beside this file, which `lockdown.py`
 * packages and the image's build checks against its installed list.
 */

const vscode = require('vscode');

/** The configuration section whose rewrite means "the practice changed".
 *
 *  It is the namespace of the two keys `package.json` contributes, and
 *  nothing here reads their values: see the note above. */
const SECTION = 'studyforge.practice';

/** Everything that is not the one editor the URL asked for.
 *
 *  `closeOtherEditors` is first and it is the whole trick. The workbench
 *  handles the URL's `openFile` payload while it starts up, well before
 *  extensions activate on `onStartupFinished` -- so by the time this runs,
 *  the payload's file already *is* the active editor. Closing the others
 *  leaves exactly the file that window was addressed with, and this
 *  extension never has to know which file that was. It runs first so that
 *  it acts before any of the closes below can move focus. */
const CONFINE = [
    'workbench.action.closeOtherEditors',
    'workbench.action.closeSidebar',
    'workbench.action.closePanel',
    'workbench.action.closeAuxiliaryBar',
];

/** When to close again after the first attempt, in milliseconds.
 *
 *  Closing once is not enough and this is why: extensions activate on
 *  `onStartupFinished`, and the workbench goes on restoring its own layout
 *  and other extensions go on opening views after that -- the Java extension
 *  raises "Opening Java Projects" and the explorer comes back. Measured: a
 *  single close at activation left the sidebar open, and the same close
 *  repeated at six seconds left it shut.
 *
 *  A decaying schedule rather than a permanent interval, so this settles the
 *  workbench and then stops. Nothing here fights the reader forever. */
const RETRIES = [250, 750, 2000, 6000, 12000];

/** Close every surrounding surface, and every editor but the active one.
 *  Each command is best-effort: a workbench without one of these still has
 *  the others. */
async function confine() {
    for (const command of CONFINE) {
        try {
            await vscode.commands.executeCommand(command);
        } catch (error) {
            /* not in this build; the rest still apply */
        }
    }
}

function apply(context) {
    confine();
    for (const delay of RETRIES) {
        const timer = setTimeout(confine, delay);
        context.subscriptions.push({ dispose: () => clearTimeout(timer) });
    }
}

function activate(context) {
    apply(context);
    context.subscriptions.push(
        vscode.workspace.onDidChangeConfiguration(function (event) {
            /* The reader moved to another practice and the study server
               rewrote the workspace settings. This extension no longer reads
               those two keys -- the URL names the file now -- but the rewrite
               is still the one signal in here that the practice changed, and
               a changed practice means a window that should be confined
               again: the workbench may have restored a surface, and the new
               URL's file wants the others closed around it. Idempotent, so
               an extra pass over an already-confined window costs nothing. */
            if (event.affectsConfiguration(SECTION)) { apply(context); }
        }),
    );
}

function deactivate() {}

module.exports = { activate, deactivate, SECTION, CONFINE, RETRIES };
