import subprocess
import sys

print("Starting NexusRAG backend on port 8080...")
subprocess.run([sys.executable, "-m", "uvicorn",
               "app.main:app", "--reload", "--port", "8080"])
