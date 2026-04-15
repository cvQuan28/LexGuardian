import subprocess
import sys

print("Starting NexusRAG backend on port 8000...")
subprocess.run([sys.executable, "-m", "uvicorn",
               "app.main:app", "--reload", "--host", "0.0.0.0", "--port", "8000"])
