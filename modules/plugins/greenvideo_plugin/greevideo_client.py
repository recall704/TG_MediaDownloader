"""
GreenVideo.cc API Payload Generator

Reverses the encryption scheme used by https://greenvideo.cc/ for the
POST /api/video/cnSimpleExtract endpoint.

Encryption flow:
  1. GET /api/auth/keys → k1 (RSA public key), k2 (RSA-encrypted AES key)
  2. Raw RSA decrypt k2 with k1 to get the AES key string
  3. AES-CBC encrypt the JSON payload {"url": "..."} with static IV
  4. RSA (PKCS1_v1_5, 245-byte chunks) encrypt the AES ciphertext
  5. Base64-encode the final result
"""

import base64
import json

from Crypto.Cipher import AES, PKCS1_v1_5
from Crypto.PublicKey import RSA
from Crypto.Util.Padding import pad
from curl_cffi import requests

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

API_KEYS_URL = "https://greenvideo.cc/api/auth/keys"
API_EXTRACT_URL = "https://greenvideo.cc/api/video/cnSimpleExtract"

# Static Initialization Vector for AES-CBC (same for all requests)
_IV_BYTES = base64.b64decode("a2Vkb3VAODk4OSE2MzIzMw==")

# RSA chunk size for PKCS1_v1_5 encryption
_RSA_CHUNK_SIZE = 245

# Default headers mimicking the browser
_DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/134.0.0.0 Safari/537.36"
    ),
    "Origin": "https://greenvideo.cc",
    "Referer": "https://greenvideo.cc/",
    "kdsystem": "GreenVideo",
    "Accept": "application/json, text/plain, */*",
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def fetch_keys() -> tuple[str, str]:
    """Fetch dynamic RSA keys from the GreenVideo auth endpoint.

    Returns:
        Tuple[str, str]: (k1, k2) where k1 is the base64-encoded RSA public
        key (X.509 DER) and k2 is the RSA-encrypted AES key.
    """
    resp = requests.get(API_KEYS_URL, headers=_DEFAULT_HEADERS, timeout=15, impersonate="chrome120")
    resp.raise_for_status()
    data = resp.json()
    return data["data"]["k1"], data["data"]["k2"]


def _build_pem(public_key_b64: str) -> str:
    """Wrap a base64-encoded public key into PEM format."""
    return f"-----BEGIN PUBLIC KEY-----\n{public_key_b64}\n-----END PUBLIC KEY-----"


def _decrypt_k2(k1_pem: str, k2_b64: str) -> str:
    """Raw RSA decrypt *k2* using the public key from *k1* to recover the AES key.

    The server encrypts the AES key with **raw** RSA (modular exponentiation,
    no padding).  We reverse that by computing ``m = c^e mod n`` and then
    extracting the UTF-8 key that follows the embedded null byte.

    Args:
        k1_pem: PEM-encoded RSA public key.
        k2_b64: Base64-encoded ciphertext of the AES key.

    Returns:
        The recovered AES key as a string.
    """
    rsa_key = RSA.import_key(k1_pem)
    c = int.from_bytes(base64.b64decode(k2_b64), byteorder="big")
    m_bytes = pow(c, rsa_key.e, rsa_key.n).to_bytes(rsa_key.size_in_bytes(), byteorder="big")
    # The plaintext has the form: 0x00 0x02 <random> 0x00 <aes_key>
    idx = m_bytes.find(b"\x00", 2)
    aes_key = m_bytes.lstrip(b"\x00").decode("utf-8") if idx == -1 else m_bytes[idx + 1 :].decode("utf-8")
    return aes_key


def generate_payload(video_url: str, k1: str | None = None, k2: str | None = None) -> str:
    """Generate the encrypted payload for ``cnSimpleExtract``.

    If *k1* and *k2* are not provided they are fetched automatically.

    Args:
        video_url: A video URL (e.g. ``https://b23.tv/ViAASmR``).
        k1: Base64 RSA public key (fetched if omitted).
        k2: Base64 RSA-encrypted AES key (fetched if omitted).

    Returns:
        The base64-encoded encrypted payload string, ready to POST as the
        JSON body of the API call.
    """
    if k1 is None or k2 is None:
        k1, k2 = fetch_keys()

    k1_pem = _build_pem(k1)

    # -- 1. Recover the per-session AES key (raw RSA decryption) --
    aes_key_str = _decrypt_k2(k1_pem, k2)

    # -- 2. AES-CBC encrypt the JSON payload --
    json_string = json.dumps({"url": video_url}, separators=(",", ":"), ensure_ascii=False)
    aes_cipher = AES.new(aes_key_str.encode("utf-8"), AES.MODE_CBC, _IV_BYTES)
    padded_plaintext = pad(json_string.encode("utf-8"), AES.block_size)
    aes_encrypted_b64 = base64.b64encode(aes_cipher.encrypt(padded_plaintext)).decode("utf-8")

    # -- 3. RSA (PKCS1_v1_5) encrypt the AES ciphertext in chunks --
    rsa_cipher = PKCS1_v1_5.new(RSA.import_key(k1_pem))
    data_bytes = aes_encrypted_b64.encode("utf-8")
    chunks = (data_bytes[i : i + _RSA_CHUNK_SIZE] for i in range(0, len(data_bytes), _RSA_CHUNK_SIZE))
    rsa_encrypted = b"".join(rsa_cipher.encrypt(chunk) for chunk in chunks)

    # -- 4. Base64-encode the final payload --
    return base64.b64encode(rsa_encrypted).decode("utf-8")


def extract_video(video_url: str, k1: str | None = None, k2: str | None = None) -> dict:
    """Call the GreenVideo API and return the parsed response.

    This is a convenience wrapper that generates the payload and POSTs it.

    Returns:
        The JSON response dict (decoded from ``resp.json()``).
    """
    payload = generate_payload(video_url, k1=k1, k2=k2)
    headers = {**_DEFAULT_HEADERS, "Content-Type": "application/json"}
    resp = requests.post(API_EXTRACT_URL, json=payload, headers=headers, timeout=30, impersonate="chrome120")
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# CLI entry point (for quick testing)
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Generate encrypted payload for GreenVideo.cc")
    parser.add_argument(
        "url",
        nargs="?",
        default="https://b23.tv/ViAASmR",
        help="Video URL (default: https://b23.tv/ViAASmR)",
    )
    args = parser.parse_args()

    payload = generate_payload(args.url)
    print(payload)
