import socket, subprocess, sys

def get_lan_ip():
    try:
        host = socket.gethostname()
        infos = socket.getaddrinfo(host, None, socket.AF_INET)
        ips = [x[4][0] for x in infos if not x[4][0].startswith("127.")]
        for ip in ips:
            if ip.startswith(("192.168.", "10.")) or ip.startswith("172."):
                return ip
        return ips[0] if ips else "127.0.0.1"
    except Exception:
        return "127.0.0.1"

ip = get_lan_ip()
print()
print("=" * 64)
print("HY DYNAMIC12 USA V2.1 MOBILE")
print("iPhone Safari address:")
print(f"http://{ip}:8501")
print("PC and iPhone must be connected to the same Wi-Fi.")
print("=" * 64)
print()

cmd = [
    sys.executable, "-m", "streamlit", "run", "app.py",
    "--server.address=0.0.0.0",
    "--server.port=8501",
    "--server.headless=true",
    "--browser.gatherUsageStats=false",
]
raise SystemExit(subprocess.call(cmd))
