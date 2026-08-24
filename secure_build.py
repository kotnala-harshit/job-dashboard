#!/usr/bin/env python3

import base64
import hashlib
import html
import json
import os
import re
import shutil
from pathlib import Path

try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError:
    raise SystemExit(
        "cryptography package missing.\n"
        "Install with: python3 -m pip install cryptography"
    )


ROOT = Path(__file__).resolve().parent
OUT = Path(
    os.environ.get(
        "SECURE_OUTPUT_DIR",
        ROOT / "secure_site",
    )
)

USERNAME = os.environ.get("SITE_USERNAME", "").strip()
PASSWORD = os.environ.get("SITE_PASSWORD", "")

if not USERNAME:
    raise SystemExit("SITE_USERNAME is required")

if len(PASSWORD) < 16:
    raise SystemExit(
        "SITE_PASSWORD must be at least 16 characters.\n"
        "20+ characters is strongly recommended."
    )


# ------------------------------------------------------------------
# Load original dashboard.
# ------------------------------------------------------------------

source_html = (ROOT / "index.html").read_text(
    encoding="utf-8"
)


# ------------------------------------------------------------------
# Detect local JSON requests used by the dashboard.
# Also explicitly include data.json.
# ------------------------------------------------------------------

json_names = {"data.json"}

for match in re.findall(
    r"""['"]([^'"]+\.json(?:\?[^'"]*)?)['"]""",
    source_html,
    flags=re.I,
):
    name = match.split("?", 1)[0]

    if (
        "://" not in name
        and not name.startswith("/")
        and (ROOT / name).is_file()
    ):
        json_names.add(name)


bundled_json = {}

for name in sorted(json_names):
    path = ROOT / name

    if not path.exists():
        continue

    try:
        bundled_json[name] = json.loads(
            path.read_text(encoding="utf-8")
        )
    except Exception as exc:
        raise SystemExit(
            f"Unable to bundle {name}: {exc}"
        )


if "data.json" not in bundled_json:
    raise SystemExit(
        "data.json could not be bundled"
    )


# ------------------------------------------------------------------
# Inject protected in-memory fetch layer BEFORE original scripts.
#
# Calls such as fetch("data.json") are answered from decrypted memory.
# No plaintext data.json needs to exist on the deployed website.
# ------------------------------------------------------------------

bootstrap = """
<script>
(() => {
    const __SECURE_JSON_FILES__ =
        __SECURE_JSON_PLACEHOLDER__;

    const originalFetch = window.fetch.bind(window);

    window.fetch = async function(input, init) {
        let raw = "";

        if (typeof input === "string") {
            raw = input;
        } else if (input && input.url) {
            raw = input.url;
        }

        try {
            const u = new URL(raw, window.location.href);
            const path = u.pathname
                .replace(/^\\/+/, "")
                .split("/")
                .pop();

            if (
                path &&
                Object.prototype.hasOwnProperty.call(
                    __SECURE_JSON_FILES__,
                    path
                )
            ) {
                return new Response(
                    JSON.stringify(
                        __SECURE_JSON_FILES__[path]
                    ),
                    {
                        status: 200,
                        headers: {
                            "Content-Type":
                                "application/json"
                        }
                    }
                );
            }
        } catch (_) {}

        return originalFetch(input, init);
    };
})();
</script>
"""

bootstrap = bootstrap.replace(
    "__SECURE_JSON_PLACEHOLDER__",
    json.dumps(
        {
            Path(k).name: v
            for k, v in bundled_json.items()
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ),
)


if "<head" in source_html.lower():
    head_close = re.search(
        r"<head[^>]*>",
        source_html,
        flags=re.I,
    )

    insert_at = head_close.end()

    protected_html = (
        source_html[:insert_at]
        + bootstrap
        + source_html[insert_at:]
    )
else:
    protected_html = bootstrap + source_html


# ------------------------------------------------------------------
# Encrypt complete dashboard HTML.
#
# PBKDF2-HMAC-SHA256:
#   600,000 iterations
#
# AES-256-GCM:
#   authenticated encryption
# ------------------------------------------------------------------

salt = os.urandom(16)
nonce = os.urandom(12)

iterations = 600_000

key = hashlib.pbkdf2_hmac(
    "sha256",
    PASSWORD.encode("utf-8"),
    salt + USERNAME.lower().encode("utf-8"),
    iterations,
    dklen=32,
)

aes = AESGCM(key)

ciphertext = aes.encrypt(
    nonce,
    protected_html.encode("utf-8"),
    b"ireland-job-radar-v1",
)


# Never publish plaintext build leftovers.
if OUT.exists():
    shutil.rmtree(OUT)

OUT.mkdir(parents=True)


payload = {
    "version": 1,
    "iterations": iterations,
    "salt": base64.b64encode(salt).decode(),
    "nonce": base64.b64encode(nonce).decode(),
    "ciphertext": base64.b64encode(ciphertext).decode(),
}

(OUT / "payload.json").write_text(
    json.dumps(
        payload,
        separators=(",", ":"),
    ),
    encoding="utf-8",
)


# ------------------------------------------------------------------
# Copy only non-sensitive local static files referenced by index.html.
# JSON files deliberately excluded.
# ------------------------------------------------------------------

asset_patterns = [
    r"""src=['"]([^'"]+)['"]""",
    r"""href=['"]([^'"]+)['"]""",
]

assets = set()

for pattern in asset_patterns:
    for value in re.findall(
        pattern,
        source_html,
        flags=re.I,
    ):
        value = value.split("?", 1)[0].split("#", 1)[0]

        if (
            not value
            or "://" in value
            or value.startswith("//")
            or value.startswith("#")
            or value.startswith("data:")
            or value.startswith("/")
        ):
            continue

        path = ROOT / value

        if not path.is_file():
            continue

        if path.suffix.lower() in {
            ".json",
            ".csv",
            ".py",
            ".yml",
            ".yaml",
        }:
            continue

        assets.add(value)


for asset in assets:
    src = ROOT / asset
    dst = OUT / asset

    dst.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    shutil.copy2(src, dst)


# ------------------------------------------------------------------
# Public login shell.
#
# No password or encryption key appears here.
# ------------------------------------------------------------------

username_digest = hashlib.sha256(
    USERNAME.lower().encode("utf-8")
).hexdigest()


login_html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta
    name="viewport"
    content="width=device-width,initial-scale=1"
>
<meta name="robots" content="noindex,nofollow">
<title>Private Job Radar</title>

<style>
:root {{
    color-scheme: dark;
    font-family:
        Inter,
        system-ui,
        -apple-system,
        BlinkMacSystemFont,
        "Segoe UI",
        sans-serif;
}}

* {{
    box-sizing: border-box;
}}

body {{
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background:
        radial-gradient(
            circle at top,
            #182133,
            #070a10 55%
        );
    color: #f4f7fb;
}}

.login {{
    width: min(420px, calc(100vw - 32px));
    padding: 32px;
    background: rgba(17,22,32,.94);
    border: 1px solid rgba(255,255,255,.12);
    border-radius: 18px;
    box-shadow:
        0 24px 80px rgba(0,0,0,.45);
}}

h1 {{
    margin: 0 0 8px;
    font-size: 26px;
}}

.subtitle {{
    margin: 0 0 26px;
    color: #aeb8c8;
    line-height: 1.5;
}}

label {{
    display: block;
    margin: 15px 0 7px;
    color: #cad2df;
    font-size: 14px;
}}

input {{
    width: 100%;
    padding: 13px 14px;
    border-radius: 10px;
    border: 1px solid #394355;
    background: #0c111a;
    color: white;
    font: inherit;
}}

input:focus {{
    outline: 2px solid #779cff;
    border-color: transparent;
}}

button {{
    width: 100%;
    margin-top: 22px;
    padding: 13px;
    border: 0;
    border-radius: 10px;
    background: #e8edf8;
    color: #10151d;
    font-weight: 700;
    font-size: 15px;
    cursor: pointer;
}}

button:disabled {{
    opacity: .55;
    cursor: wait;
}}

#error {{
    min-height: 22px;
    margin-top: 15px;
    color: #ff9696;
    font-size: 14px;
}}

.security {{
    margin-top: 22px;
    color: #788498;
    font-size: 12px;
    line-height: 1.5;
}}

.loader {{
    display: none;
    margin-top: 14px;
    color: #aeb8c8;
    font-size: 13px;
}}

.remember-row {{
    margin-top: 17px;
    display: flex;
    align-items: center;
    gap: 12px;
    flex-wrap: wrap;
}}

.remember-label {{
    display: flex;
    align-items: center;
    gap: 8px;
    margin: 0;
    cursor: pointer;
    user-select: none;
}}

.remember-label input {{
    width: auto;
    margin: 0;
}}

#rememberDays {{
    width: auto;
    min-width: 105px;
    padding: 8px 10px;
    border-radius: 8px;
    border: 1px solid #394355;
    background: #0c111a;
    color: white;
}}

#rememberDays:disabled {{
    opacity: .45;
}}

.remember-warning {{
    margin-top: 9px;
    color: #788498;
    font-size: 12px;
    line-height: 1.45;
}}
</style>
</head>

<body>

<main class="login">

<h1>Private Job Radar</h1>

<p class="subtitle">
Authorized access only.
Enter your username and password.
</p>

<form id="loginForm">

<label for="username">
Username
</label>

<input
    id="username"
    type="text"
    autocomplete="username"
    required
>

<label for="password">
Password
</label>

<input
    id="password"
    type="password"
    autocomplete="current-password"
    required
>

<div class="remember-row">

<label class="remember-label">
<input
    id="rememberDevice"
    type="checkbox"
>
Remember this device
</label>

<select
    id="rememberDays"
    aria-label="Remember duration"
    disabled
>
<option value="30">30 days</option>
<option value="60">60 days</option>
<option value="90">90 days</option>
</select>

</div>

<div class="remember-warning">
Use this only on a personal or trusted device.
</div>

<button id="submit" type="submit">
Unlock dashboard
</button>

<div class="loader" id="loader">
Decrypting securely…
</div>

<div id="error"></div>

</form>

<div class="security">
Dashboard content is AES-256-GCM encrypted.
The password is never stored in this page.
</div>

</main>

<script>

const USERNAME_HASH =
    "{username_digest}";

const AAD =
    new TextEncoder()
        .encode("ireland-job-radar-v1");


function fromBase64(value) {{
    const binary = atob(value);
    const bytes = new Uint8Array(binary.length);

    for (
        let i = 0;
        i < binary.length;
        i++
    ) {{
        bytes[i] = binary.charCodeAt(i);
    }}

    return bytes;
}}


async function sha256Hex(value) {{
    const digest =
        await crypto.subtle.digest(
            "SHA-256",
            new TextEncoder().encode(value)
        );

    return Array.from(
        new Uint8Array(digest)
    )
    .map(
        b => b
            .toString(16)
            .padStart(2, "0")
    )
    .join("");
}}



const REMEMBER_DB_NAME =
    "job-radar-auth";

const REMEMBER_STORE_NAME =
    "remembered-session";

const REMEMBER_RECORD_ID =
    "job-radar-login";


function openRememberDatabase() {{

    return new Promise(
        (resolve, reject) => {{

            const request =
                indexedDB.open(
                    REMEMBER_DB_NAME,
                    1
                );

            request.onupgradeneeded =
                event => {{

                    const db =
                        event.target.result;

                    if (
                        !db.objectStoreNames.contains(
                            REMEMBER_STORE_NAME
                        )
                    ) {{
                        db.createObjectStore(
                            REMEMBER_STORE_NAME,
                            {{
                                keyPath: "id"
                            }}
                        );
                    }}
                }};

            request.onsuccess =
                () => resolve(
                    request.result
                );

            request.onerror =
                () => reject(
                    request.error
                );
        }}
    );
}}


async function saveRememberedLogin(
    username,
    password,
    days
) {{

    const duration =
        Number(days);

    if (![30, 60, 90].includes(duration)) {{
        throw new Error(
            "Invalid remember-device duration"
        );
    }}

    /*
     * Non-extractable browser key.
     * The raw wrapping key is not exposed to JavaScript.
     */
    const wrappingKey =
        await crypto.subtle.generateKey(
            {{
                name: "AES-GCM",
                length: 256
            }},
            false,
            [
                "encrypt",
                "decrypt"
            ]
        );

    const iv =
        crypto.getRandomValues(
            new Uint8Array(12)
        );

    const encryptedPassword =
        await crypto.subtle.encrypt(
            {{
                name: "AES-GCM",
                iv: iv
            }},
            wrappingKey,
            new TextEncoder().encode(
                password
            )
        );

    const expiresAt =
        Date.now() +
        (
            duration *
            24 *
            60 *
            60 *
            1000
        );

    const db =
        await openRememberDatabase();

    try {{

        await new Promise(
            (resolve, reject) => {{

                const tx =
                    db.transaction(
                        REMEMBER_STORE_NAME,
                        "readwrite"
                    );

                tx.objectStore(
                    REMEMBER_STORE_NAME
                ).put(
                    {{
                        id:
                            REMEMBER_RECORD_ID,

                        username:
                            username,

                        key:
                            wrappingKey,

                        iv:
                            Array.from(iv),

                        encryptedPassword:
                            Array.from(
                                new Uint8Array(
                                    encryptedPassword
                                )
                            ),

                        createdAt:
                            Date.now(),

                        expiresAt:
                            expiresAt,

                        durationDays:
                            duration
                    }}
                );

                tx.oncomplete =
                    () => resolve();

                tx.onerror =
                    () => reject(
                        tx.error
                    );
            }}
        );

    }} finally {{

        db.close();

    }}
}}


async function clearRememberedLogin() {{

    try {{

        const db =
            await openRememberDatabase();

        try {{

            await new Promise(
                (resolve, reject) => {{

                    const tx =
                        db.transaction(
                            REMEMBER_STORE_NAME,
                            "readwrite"
                        );

                    tx.objectStore(
                        REMEMBER_STORE_NAME
                    ).delete(
                        REMEMBER_RECORD_ID
                    );

                    tx.oncomplete =
                        () => resolve();

                    tx.onerror =
                        () => reject(
                            tx.error
                        );
                }}
            );

        }} finally {{

            db.close();

        }}

    }} catch (_) {{}}
}}


async function loadRememberedLogin() {{

    let db = null;

    try {{

        db =
            await openRememberDatabase();

        const record =
            await new Promise(
                (resolve, reject) => {{

                    const tx =
                        db.transaction(
                            REMEMBER_STORE_NAME,
                            "readonly"
                        );

                    const request =
                        tx.objectStore(
                            REMEMBER_STORE_NAME
                        ).get(
                            REMEMBER_RECORD_ID
                        );

                    request.onsuccess =
                        () => resolve(
                            request.result || null
                        );

                    request.onerror =
                        () => reject(
                            request.error
                        );
                }}
            );

        if (!record) {{
            return null;
        }}

        if (
            !record.expiresAt ||
            Date.now() >=
                Number(record.expiresAt)
        ) {{

            db.close();
            db = null;

            await clearRememberedLogin();

            return null;
        }}

        const decryptedPassword =
            await crypto.subtle.decrypt(
                {{
                    name: "AES-GCM",
                    iv:
                        new Uint8Array(
                            record.iv
                        )
                }},
                record.key,
                new Uint8Array(
                    record.encryptedPassword
                )
            );

        return {{
            username:
                record.username,

            password:
                new TextDecoder().decode(
                    decryptedPassword
                ),

            expiresAt:
                Number(record.expiresAt),

            durationDays:
                Number(
                    record.durationDays
                )
        }};

    }} catch (_) {{

        return null;

    }} finally {{

        if (db) {{
            db.close();
        }}

    }}
}}


async function unlock(
    username,
    password,
    rememberDays = null
) {{

    const normalizedUsername =
        username.trim().toLowerCase();

    const usernameHash =
        await sha256Hex(
            normalizedUsername
        );

    if (usernameHash !== USERNAME_HASH) {{
        throw new Error(
            "Invalid username or password"
        );
    }}

    const response =
        await fetch(
            "payload.json",
            {{ cache: "no-store" }}
        );

    if (!response.ok) {{
        throw new Error(
            "Encrypted dashboard unavailable"
        );
    }}

    const payload =
        await response.json();

    const salt =
        fromBase64(payload.salt);

    const usernameBytes =
        new TextEncoder()
            .encode(normalizedUsername);

    const combinedSalt =
        new Uint8Array(
            salt.length +
            usernameBytes.length
        );

    combinedSalt.set(salt, 0);

    combinedSalt.set(
        usernameBytes,
        salt.length
    );

    const passwordKey =
        await crypto.subtle.importKey(
            "raw",
            new TextEncoder()
                .encode(password),
            "PBKDF2",
            false,
            ["deriveKey"]
        );

    const key =
        await crypto.subtle.deriveKey(
            {{
                name: "PBKDF2",
                hash: "SHA-256",
                salt: combinedSalt,
                iterations:
                    payload.iterations
            }},
            passwordKey,
            {{
                name: "AES-GCM",
                length: 256
            }},
            false,
            ["decrypt"]
        );

    let plaintext;

    try {{

        plaintext =
            await crypto.subtle.decrypt(
                {{
                    name: "AES-GCM",
                    iv:
                        fromBase64(
                            payload.nonce
                        ),
                    additionalData: AAD,
                    tagLength: 128
                }},
                key,
                fromBase64(
                    payload.ciphertext
                )
            );

    }} catch (_) {{

        throw new Error(
            "Invalid username or password"
        );

    }}

    /*
     * Only update remembered-device state after successful
     * AES-GCM authentication/decryption.
     *
     * null = auto-login; preserve original expiry.
     * 0    = manual login without remembering.
     * 30/60/90 = save remembered device.
     */
    if (rememberDays !== null) {{

        if (Number(rememberDays) > 0) {{

            await saveRememberedLogin(
                normalizedUsername,
                password,
                Number(rememberDays)
            );

        }} else {{

            await clearRememberedLogin();

        }}
    }}

    const dashboard =
        new TextDecoder()
            .decode(plaintext);

    document.open();

    document.write(
        dashboard
    );

    document.close();
}}


let failures = 0;
let lockedUntil = 0;


document
.getElementById("loginForm")
.addEventListener(
    "submit",
    async event => {{

        event.preventDefault();

        const now = Date.now();

        if (now < lockedUntil) {{
            const seconds =
                Math.ceil(
                    (
                        lockedUntil -
                        now
                    ) / 1000
                );

            document
                .getElementById("error")
                .textContent =
                    `Too many attempts. ` +
                    `Try again in ` +
                    `${{seconds}}s.`;

            return;
        }}

        const username =
            document
                .getElementById(
                    "username"
                )
                .value;

        const password =
            document
                .getElementById(
                    "password"
                )
                .value;

        const button =
            document
                .getElementById(
                    "submit"
                );

        const loader =
            document
                .getElementById(
                    "loader"
                );

        const error =
            document
                .getElementById(
                    "error"
                );

        button.disabled = true;
        loader.style.display = "block";
        error.textContent = "";

        try {{

            const remember =
                document
                    .getElementById(
                        "rememberDevice"
                    )
                    .checked;

            const duration =
                remember
                    ? Number(
                        document
                            .getElementById(
                                "rememberDays"
                            )
                            .value
                    )
                    : 0;

            await unlock(
                username,
                password,
                duration
            );

            failures = 0;

        }} catch (err) {{

            failures += 1;

            if (failures >= 5) {{
                lockedUntil =
                    Date.now() +
                    30_000;

                failures = 0;
            }}

            error.textContent =
                err.message ||
                "Unable to unlock";

            button.disabled = false;

            loader.style.display =
                "none";
        }}
    }}
);

document
.getElementById(
    "rememberDevice"
)
.addEventListener(
    "change",
    event => {{

        document
            .getElementById(
                "rememberDays"
            )
            .disabled =
                !event.target.checked;
    }}
);


(async () => {{

    const loader =
        document
            .getElementById(
                "loader"
            );

    const error =
        document
            .getElementById(
                "error"
            );

    const remembered =
        await loadRememberedLogin();

    if (!remembered) {{
        return;
    }}

    loader.textContent =
        "Unlocking remembered device…";

    loader.style.display =
        "block";

    try {{

        /*
         * null deliberately prevents successful visits
         * from extending the original expiry date.
         */
        await unlock(
            remembered.username,
            remembered.password,
            null
        );

    }} catch (_) {{

        await clearRememberedLogin();

        loader.style.display =
            "none";

        error.textContent =
            "Saved login expired or credentials changed. Please sign in again.";
    }}

}})();


</script>

</body>
</html>
"""


(OUT / "index.html").write_text(
    login_html,
    encoding="utf-8",
)


# ------------------------------------------------------------------
# Safety verification.
# ------------------------------------------------------------------

for forbidden in (
    "data.json",
    "seen_jobs.json",
    "company_history.json",
    "profile.json",
    "sponsorship_history.json",
    "official_permit_stats.json",
):

    if (OUT / forbidden).exists():
        raise SystemExit(
            f"SECURITY FAILURE: "
            f"{forbidden} exists plaintext "
            f"in secure output"
        )


print()
print("Secure build complete")
print("Output:", OUT)
print("Bundled JSON:", ", ".join(sorted(bundled_json)))
print("Assets copied:", len(assets))
print("PBKDF2 iterations:", iterations)
print("Encryption: AES-256-GCM")
