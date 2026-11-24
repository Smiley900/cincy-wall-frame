#!/usr/bin/env python3
"""Check a file downloaded from Dropbox against the content_hash Dropbox reports for it.

Usage: python3 tools/check_download.py <file> <content_hash>
Prints "match" and exits 0 when they agree; prints "MISMATCH" and exits 1 otherwise.
(Dropbox's content hash: SHA-256 of each 4 MB block, then SHA-256 of those digests joined.)
"""
import hashlib, sys

def content_hash(path, block=4 * 1024 * 1024):
    digests = b""
    with open(path, "rb") as f:
        while True:
            chunk = f.read(block)
            if not chunk:
                break
            digests += hashlib.sha256(chunk).digest()
    return hashlib.sha256(digests).hexdigest()

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__); sys.exit(2)
    got = content_hash(sys.argv[1])
    ok = got == sys.argv[2].strip().lower()
    print("match" if ok else f"MISMATCH: file is {got}")
    sys.exit(0 if ok else 1)
