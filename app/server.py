import os
import sys
import runpy

os.environ.setdefault('SIGN_SERVER', 'http://127.0.0.1:9099')
os.environ.setdefault('BIND_HOST', '127.0.0.1')
os.environ.setdefault('PORT', '8000')

cur_dir = os.path.dirname(os.path.abspath(__file__))
if cur_dir not in sys.path:
    sys.path.insert(0, cur_dir)

try:
    import licensing
    licensing.enforced = lambda: False
    licensing.is_active_cached = lambda: True
    licensing.check_download = lambda series_id: {
        "allowed": True,
        "licensed": True,
        "reason": "unlimited",
        "free_used": 0,
        "free_limit": 999999
    }
    licensing.usage = lambda *a, **kw: {
        "configured": False,
        "licensed": True,
        "free_limit": 999999,
        "free_used": 0,
        "remaining": 999999,
        "key_masked": "VIP-UNLIMITED",
        "device_label": "VIP / Unlimited"
    }
except Exception as e:
    print("[patch] licensing patch notice:", e)

pyc_path = os.path.join(cur_dir, "server.pyc")
if os.path.exists(pyc_path):
    runpy.run_path(pyc_path, run_name="__main__")
