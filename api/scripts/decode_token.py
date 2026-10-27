"""Show the claims in a Clerk session token, to confirm where the active organization lives.

    pbpaste | api/.venv/bin/python api/scripts/decode_token.py      # token on the clipboard
    api/.venv/bin/python api/scripts/decode_token.py < token.txt

Reads the token from stdin (so it never lands in shell history) and decodes it WITHOUT
verifying the signature: this is for looking, the API does the verifying. Use your own dev
token only. Prints claim names and values; the token itself is never printed.
"""

import json
import sys

import jwt

token = sys.stdin.read().strip().removeprefix("Bearer ").strip()
if not token:
    sys.exit("paste a token on stdin")

header = jwt.get_unverified_header(token)
claims = jwt.decode(token, options={"verify_signature": False})
print("header:", {k: header[k] for k in ("alg", "kid") if k in header})
print("claims:")
for name, value in claims.items():
    print(f"  {name}: {json.dumps(value)}")

if isinstance(claims.get("o"), dict):
    print("\nlayout: v2 (org nested under `o`)  ->", claims["o"])
elif "org_id" in claims:
    print("\nlayout: v1 (org_id / org_role at top level)  ->", claims["org_id"], claims.get("org_role"))
else:
    print("\nNO ACTIVE ORGANIZATION in this token: the API will answer 403. Pick or create an org.")
