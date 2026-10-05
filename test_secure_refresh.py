"""Browser integration: python3 test_secure_refresh.py (cryptography, playwright/Chromium). Uses dummy credentials."""
import base64, hashlib, json, os, subprocess, sys, tempfile, threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parent
PASSWORD='local-build-verification-only'
USERNAME='audit-test'
AAD=b'ireland-job-radar-v1'
with tempfile.TemporaryDirectory() as directory:
    out=Path(directory)
    subprocess.run([sys.executable,str(ROOT/'secure_build.py')],env={**os.environ,'SITE_USERNAME':USERNAME,'SITE_PASSWORD':PASSWORD,'SECURE_OUTPUT_DIR':directory},check=True)
    payload=json.loads((out/'payload.json').read_text())
    def key(p):
        return hashlib.pbkdf2_hmac('sha256',PASSWORD.encode(),base64.b64decode(p['salt'])+USERNAME.encode(),p['iterations'],32)
    html=AESGCM(key(payload)).decrypt(base64.b64decode(payload['nonce']),base64.b64decode(payload['ciphertext']),AAD).decode()
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=directory))
    threading.Thread(target=server.serve_forever,daemon=True).start()
    try:
        with sync_playwright() as p:
            browser=p.chromium.launch()
            page=browser.new_page()
            errors=[]
            page.on('pageerror',lambda error: errors.append(str(error)))
            page.goto(f'http://127.0.0.1:{server.server_port}/')
            assert page.request.get(f'http://127.0.0.1:{server.server_port}/data.json').status == 404
            assert page.evaluate("async () => {try {await unlock('audit-test','wrong-password',0); return false;} catch(e) {return true;}}")
            page.evaluate("unlock('audit-test','local-build-verification-only',0)")
            page.wait_for_function("typeof ALL_JOBS !== 'undefined' && ALL_JOBS.length > 0")
            title=page.evaluate('ALL_JOBS[0].title')
            page.evaluate("JOB_STATES[jobId(ALL_JOBS[0])] = 'saved'; document.getElementById('fCompany').value = ALL_JOBS[0].company")
            company=page.locator('#fCompany').input_value()
            changed=html.replace(json.dumps(title,ensure_ascii=False)[1:-1], 'REFRESH TEST '+json.dumps(title,ensure_ascii=False)[1:-1])
            assert changed != html
            updated={**payload,'salt':base64.b64encode(os.urandom(16)).decode(),'nonce':base64.b64encode(os.urandom(12)).decode()}
            updated['ciphertext']=base64.b64encode(AESGCM(key(updated)).encrypt(base64.b64decode(updated['nonce']),changed.encode(),AAD)).decode()
            (out/'payload.json').write_text(json.dumps(updated))
            page.evaluate('autoFetchJobs()')
            assert page.evaluate('ALL_JOBS[0].title') == 'REFRESH TEST '+title
            assert page.evaluate('jobState(ALL_JOBS[0])') == 'saved'
            assert page.locator('#fCompany').input_value() == company
            (out/'payload.json').write_text(json.dumps({**updated,'nonce':base64.b64encode(os.urandom(12)).decode()}))
            page.evaluate('autoFetchJobs()')
            assert 'Update failed' in page.locator('#liveStatus').inner_text()
            assert page.evaluate('ALL_JOBS[0].title') == 'REFRESH TEST '+title
            (out/'payload.json').write_text(json.dumps(updated))
            page.evaluate('autoFetchJobs()')
            assert 'Up to date' in page.locator('#liveStatus').inner_text()
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
print('Encrypted live refresh, key rotation, saved state, filters and failure recovery passed')
