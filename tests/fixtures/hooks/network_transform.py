import urllib.request
import sys

try:
    urllib.request.urlopen("http://example.com", timeout=2)
    sys.stdout.write('{"network_ok": true}')
except Exception as e:
    sys.stdout.write(f'{{"network_error": "{e}"}}')
