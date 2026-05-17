import json
import sys

data = json.loads(sys.stdin.read())
data["echoed"] = True
sys.stdout.write(json.dumps(data))
