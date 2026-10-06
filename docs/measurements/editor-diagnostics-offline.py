"""Read the diagnostics a profile's editor image shows for a Python and a TypeScript file with the network cut off.

    python3 docs/measurements/editor-diagnostics-offline.py <editor image> [file ...]
    SCREENSHOTS=<directory> python3 docs/measurements/editor-diagnostics-offline.py <editor image>

The editor runs on an internal network (no route out) and a small relay container publishes its port; a
headless browser opens each planted file and reads the editor's own error squiggles and Problems count.
Exit 0 only when the files with a planted error show one and the clean files show none. Needs Docker
(`DOCKER_CONTEXT` picks the engine) and a Chrome or Chromium on the host. Everything it creates carries the
label `com.local.scratch=editor-diagnostics` and is removed afterwards.
"""
import contextlib, subprocess, sys, time, uuid, json, os, base64
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "docker" / "editor"))
import activation, cdp, probe, engine

IMAGE = sys.argv[1]
LABEL = "com.local.scratch=editor-diagnostics"
FILES = {
 "bad.ts": "const count: number = 'not a number';\nconsole.log(count.toFixed(2));\n",
 "ok.ts": "const count: number = 1;\nconsole.log(count.toFixed(2));\n",
 "bad.py": "def add(a: int, b: int) -> int:\n    return a + b\n\nx: str = add(1, 2)\nprint(undefined_name)\n",
 "ok.py": "def add(a: int, b: int) -> int:\n    return a + b\n\nprint(add(1, 2))\n",
 "bad_member.py": "import anthropic\nclient = anthropic.Anthropic(api_key='x')\nclient.mess\n",
 "ok_import.py": "import anthropic\nimport pydantic\nprint(anthropic.__version__, pydantic.VERSION)\n",
}
ASK = sys.argv[2:] or sorted(FILES, key=lambda n: (not n.startswith("bad"), n))
SQUIG = """(() => ({err: document.querySelectorAll('.monaco-editor .squiggly-error').length,
  warn: document.querySelectorAll('.monaco-editor .squiggly-warning').length,
  status: [...document.querySelectorAll('.statusbar-item')].map(e => e.getAttribute('aria-label')||e.innerText).filter(t => /error|warning|problem/i.test(t||'')),
  lang: (document.querySelector('#status\\\\.editor\\\\.mode')||{}).innerText || null}))()"""

def sh(*a, check=True):
    return subprocess.run(["docker", *a], capture_output=True, text=True, stdin=subprocess.DEVNULL)

@contextlib.contextmanager
def offline_editor():
    tag = uuid.uuid4().hex[:8]
    net, ed, relay, vol = f"diag-int-{tag}", f"diag-ed-{tag}", f"diag-rl-{tag}", f"diag-ed-{tag}"
    try:
        sh("network", "create", "--internal", "--label", LABEL, net)
        engine.seed(IMAGE, vol, FILES)
        engine.start(IMAGE, ed, vol, "--network", net, "--label", LABEL)
        code = ("import socket,threading\n"
                "def pump(a,b):\n"
                "  try:\n"
                "    while True:\n"
                "      d=a.recv(65536)\n"
                "      if not d: break\n"
                "      b.sendall(d)\n"
                "  except OSError: pass\n"
                "  finally:\n"
                "    for s in (a,b):\n"
                "      try: s.close()\n"
                "      except OSError: pass\n"
                f"L=socket.socket(); L.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1); L.bind(('0.0.0.0',8080)); L.listen(50)\n"
                "def serve(c):\n"
                "  try: u=socket.create_connection(('%s',8080))\n"
                "  except OSError:\n"
                "    c.close(); return\n"
                "  threading.Thread(target=pump,args=(u,c),daemon=True).start(); pump(c,u)\n"
                "while True:\n"
                "  c,_=L.accept(); threading.Thread(target=serve,args=(c,),daemon=True).start()\n" % ed)
        r = sh("run", "-d", "--name", relay, "--label", LABEL, "-p", "127.0.0.1::8080", "--entrypoint", "python3", IMAGE, "-c", code)
        assert r.returncode == 0, r.stderr
        sh("network", "connect", net, relay)
        port = activation.published_port(relay)
        try:
            activation.wait_for_health(port)
        except engine.Refused:
            for who in (ed, relay):
                print(f"--- logs of {who}:\n" + (sh("logs", "--tail", "15", who).stdout or "") + (sh("logs", "--tail", "15", who).stderr or ""))
            raise
        yield ed, port
    finally:
        sh("rm", "-f", relay, ed); sh("volume", "rm", "-f", vol); sh("network", "rm", net)

results = {}
with offline_editor() as (ed, port):
    egress = sh("exec", ed, "bash", "-c", "timeout 5 bash -c 'exec 3<>/dev/tcp/1.1.1.1/443' && echo REACHED || echo NO-EGRESS")
    print("egress from the editor container:", egress.stdout.strip(), egress.stderr.strip()[:100])
    found = activation.browser()
    for name in ASK:
        dbg = probe.free_port()
        url = activation.workbench_url(port, name=name)
        with activation.Browser(found, f"--remote-debugging-port={dbg}", "--window-size=1400,900", url):
            page = cdp.wait_for_target(dbg, "127.0.0.1")
            with cdp.Session(page["webSocketDebuggerUrl"]) as s:
                s.call("Runtime.enable")
                sess = type("S", (), {})()
                # wait for editor
                t0 = time.time(); box = None
                while time.time() - t0 < 120:
                    box = cdp.evaluate(s, probe._EDITOR_BOX)
                    if box: break
                    time.sleep(2)
                last = None
                for i in range(30 if name.startswith("bad") else 9):   # a planted error: up to ~90 s; a clean file: a fixed 27 s
                    time.sleep(3)
                    last = cdp.evaluate(s, SQUIG)
                    if last["err"]: break
                print(f"{name}: editor_open={bool(box)} after={int(time.time()-t0)}s -> {json.dumps(last)}")
                results[name] = last
                if os.environ.get("SCREENSHOTS"):
                    shot = s.call("Page.captureScreenshot", {"format": "png"})
                    (Path(os.environ["SCREENSHOTS"]) / f"{name}.png").write_bytes(base64.b64decode(shot["data"]))
    stats = sh("stats", "--no-stream", "--format", "{{.MemUsage}}", ed)
    print("editor memory (last file open):", stats.stdout.strip())

bad = [n for n in results if n.startswith("bad") and not results[n]["err"]]
dirty = [n for n in results if n.startswith("ok") and results[n]["err"]]
print("RESULT", "ok" if not bad and not dirty else f"missing diagnostics: {bad}; false errors: {dirty}")
sys.exit(0 if not bad and not dirty else 1)
