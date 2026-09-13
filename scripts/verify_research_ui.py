"""Headless local UI smoke checks; no model calls or paid requests.

Run with the backend serving the built UI on 8079, or pass --base-url. Screenshots are written to
ignored data/verification. Uses the installed Chrome and websockets package.
"""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import tempfile
import time

import httpx
from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--base-url", default="http://127.0.0.1:8079")
args = parser.parse_args()
BASE_URL = args.base_url.rstrip("/")
OUT = ROOT / "data" / "verification"
OUT.mkdir(parents=True, exist_ok=True)
profile = Path(tempfile.mkdtemp(prefix="research-chrome-", dir=OUT))
chrome = Path("C:/Program Files/Google/Chrome/Application/chrome.exe")
process = subprocess.Popen([
    str(chrome), "--headless=new", "--disable-gpu", "--no-first-run", "--no-default-browser-check",
    "--remote-debugging-port=0", f"--user-data-dir={profile}", "about:blank",
], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
socket = None
try:
    deadline = time.monotonic() + 20
    active = profile / "DevToolsActivePort"
    while not active.exists():
        if time.monotonic() > deadline:
            raise RuntimeError("Chrome debugging endpoint did not become available")
        time.sleep(.1)
    port = active.read_text().splitlines()[0]
    pages = httpx.get(f"http://127.0.0.1:{port}/json").json()
    socket = connect(next(p["webSocketDebuggerUrl"] for p in pages if p["type"] == "page"), max_size=20_000_000)
    sequence = 0

    def cdp(method, params=None):
        global sequence
        sequence += 1
        socket.send(json.dumps({"id": sequence, "method": method, "params": params or {}}))
        while True:
            event = json.loads(socket.recv(timeout=20))
            if event.get("id") == sequence:
                if "error" in event:
                    raise RuntimeError(event["error"])
                return event.get("result", {})

    def js(expression):
        value = cdp("Runtime.evaluate", {"expression": expression, "returnByValue": True, "awaitPromise": True})
        if "exceptionDetails" in value:
            raise AssertionError(value["exceptionDetails"])
        return value["result"].get("value")

    def until(expression):
        deadline = time.monotonic() + 15
        while not js(expression):
            if time.monotonic() > deadline:
                raise AssertionError("UI did not reach expected state: " + expression)
            time.sleep(.1)

    def screenshot(name):
        data = cdp("Page.captureScreenshot", {"format": "png"})["data"]
        (OUT / name).write_bytes(base64.b64decode(data))

    def ask(question):
        js("(() => { const input=document.querySelector('input[aria-label=\"Research question\"]'); "
           "Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set.call(input," + json.dumps(question) + ");"
           "input.dispatchEvent(new Event('input',{bubbles:true})); })()")
        js("document.querySelector('form.rw-search').requestSubmit()")

    cdp("Page.enable")
    # Only the optional draft response is a UI fixture. All research questions,
    # graph results and evidence passages below use the real local server.
    cdp("Page.addScriptToEvaluateOnNewDocument", {"source": """
      window.__nativeFetch = window.fetch.bind(window);
      window.fetch = async (input, init) => {
        const url = typeof input === 'string' ? input : input.url;
        if (url.endsWith('/api/simulate-target')) {
          window.__draftRequest = JSON.parse(init.body);
          if (!window.__draftFixture) throw new Error('No draft fixture installed; paid calls are forbidden in UI tests');
          return Response.json(window.__draftFixture);
        }
        if (url.endsWith('/api/research') && window.__failResearch) {
          window.__failResearch = false;
          return new Response('Fixture service unavailable', {status: 503});
        }
        const response = await window.__nativeFetch(input, init);
        if (url.endsWith('/api/research/capabilities')) {
          const body = await response.json();
          body.research_draft_configured = true;
          return Response.json(body);
        }
        return response;
      };
    """})
    cdp("Emulation.setDeviceMetricsOverride", {"width": 1600, "height": 1000, "deviceScaleFactor": 1, "mobile": False})
    cdp("Page.navigate", {"url": BASE_URL + "/"})
    # The intervention answer names the readout, not the perturbed source.
    until("document.querySelector('.rw-answer')?.textContent.includes('GFAP')")
    assert js("document.querySelectorAll('.rw-svg-node').length") > 1
    screenshot("research-workspace.png")
    ask("What does GFAP activate?")
    until("document.querySelector('.rw-page-heading')?.textContent.includes('GFAP → activates downstream')")
    assert js("document.querySelector('.rw-page-heading').textContent.includes('GFAP')")
    js("document.querySelector('.rw-svg-edge').dispatchEvent(new MouseEvent('click',{bubbles:true}))")
    until("document.querySelector('.rw-details blockquote') !== null")
    assert js("document.querySelector('.rw-details .rw-quote a') !== null")
    screenshot("gfap-evidence.png")
    ask("What happens to SQSTM1 if I decrease TBK1?")
    until("document.querySelector('.rw-answer')?.textContent.includes('SQSTM1')")
    assert js("document.querySelector('.rw-answer').textContent.includes('both increased and decreased')")
    screenshot("intervention-hypothesis.png")
    ask("What does MISSING_ENTITY activate?")
    until("document.querySelector('.rw-empty')?.textContent.includes('MISSING_ENTITY')")
    assert js("document.querySelector('.rw-canvas') === null")
    ask("Does TBK1 reduce TARDBP aggregation?")
    until("document.querySelector('.rw-empty')?.textContent.includes('TARDBP aggregation')")
    assert js("document.querySelector('.rw-canvas') === null")
    ask("Which targets could reduce TARDBP?")
    until("document.querySelector('.rw-answer')?.textContent.includes('TARDBP')")
    assert js("document.querySelector('.rw-answer').textContent.includes('0 chemical entities')")
    # Export captures exactly the result shown, including its snapshot and citations.
    js("window.__createObjectURL = URL.createObjectURL; URL.createObjectURL = blob => {window.__exportBlob = blob; return window.__createObjectURL(blob);}")
    js("[...document.querySelectorAll('.rw-tools button')].find(b=>b.textContent.includes('Export')).click()")
    exported = js("window.__exportBlob.text().then(JSON.parse)")
    assert exported["query"] == "Which targets could reduce TARDBP?"
    assert all(link["evidence_ids"] for link in exported["links"])
    # Select a real cited claim omitted from this bounded research canvas.
    current_ids = {e["id"] for e in exported["links"]}
    candidate = httpx.post(BASE_URL + "/api/research", json={"query": "Show mechanism of TBK1"}, timeout=20).json()
    cited = next(e for e in candidate["links"] if e["id"] not in current_ids)
    detail = httpx.get(BASE_URL + f"/edges/{cited['id']}/evidence?limit=100").json()
    passages = [{"id": e["evidence_id"], "claim_id": cited["id"], "quote": e["quote"],
                 "publication_id": e["document"]["id"], "publication_url": e["link"],
                 "context_id": "ctx_unknown", "review_status": "unreviewed"}
                for e in detail["evidence"] if e["evidence_id"] in cited["evidence_ids"]]
    assert passages
    fixture = {"snapshot": exported["snapshot"], "method": "signed_path_hypothesis", "nodes": candidate["nodes"],
               "links": [dict(cited, belief_score=cited["belief"])], "evidence": passages,
               "warnings": ["Synthetic UI draft fixture; no provider request."], "errors": [],
               "synthesis_status": "generated", "synthesis": {"biological_rationale": [
                   {"text": "UI fixture: inspect a citation outside the displayed routes.", "claim_ids": [cited["id"]],
                    "evidence_ids": [passages[0]["id"]], "basis": "evidence"}], "validation_protocol": None,
                   "confidence_assessment": "UI fixture only", "assumptions": [], "limitations": []}}
    js("window.__draftFixture = " + json.dumps(fixture))
    js("[...document.querySelectorAll('.rw-nav-item')].find(b=>b.textContent==='Experiment ideas').click()")
    until("document.querySelector('.rw-brief-question') !== null")
    screenshot("experiment-brief.png")
    js("document.querySelector('.rw-experiment .rw-primary').click()")
    until("document.querySelector('.rw-generated') !== null")
    assert js("window.__draftRequest.snapshot_id") == exported["snapshot"]["id"]
    js("[...document.querySelectorAll('.rw-generated button')].find(b=>b.textContent==='Inspect cited claim').click()")
    until("document.querySelector('.rw-details blockquote') !== null")
    assert js("document.querySelector('.rw-details').textContent.includes('Relationship details')")
    assert js("document.querySelector('.rw-details blockquote').textContent") in {e["quote"] for e in passages}
    screenshot("draft-citation.png")
    js("[...document.querySelectorAll('.rw-nav-item')].find(b=>b.textContent==='Experiment ideas').click()")
    cdp("Emulation.setDeviceMetricsOverride", {"width": 390, "height": 844, "deviceScaleFactor": 1, "mobile": True})
    screenshot("research-mobile.png")
    assert js("document.documentElement.scrollWidth <= 392")
    js("window.__failResearch = true")
    ask("What does GFAP activate?")
    until("document.querySelector('.rw-empty[role=alert]') !== null")
    assert js("document.querySelector('.rw-canvas') === null")
    js("[...document.querySelectorAll('.rw-empty button')].find(b=>b.textContent==='Retry question').click()")
    until("document.querySelector('.rw-answer')?.textContent.includes('GFAP')")
    report = {"ui_checks": "passed", "screenshots": str(OUT), "paid_calls": 0,
              "draft_provider": "synthetic UI fixture", "research_api": "live local snapshot",
              "checks": ["default graph", "query direction", "evidence links", "missing entity", "distinct readout",
                         "upstream candidates", "JSON export", "experiment brief", "draft citation outside canvas",
                         "mobile width", "HTTP failure", "retry"]}
    (OUT / "research-ui-checks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report))
finally:
    if socket:
        socket.close()
    process.terminate()
    process.wait(timeout=10)
