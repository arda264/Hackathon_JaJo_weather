"""Build the pitch deck end to end: route map, then the four-slide deck."""
import subprocess
import sys

for script in ("slides/plot_routes.py", "slides/make_slides.py"):
    print("=== " + script)
    if subprocess.run([sys.executable, script]).returncode:
        sys.exit("failed: " + script)
