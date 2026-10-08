# Experimental examples

`xrdp/rdaccess_speak_test.py` is a manual NVDA speech transport smoke test for the experimental xrdp/rdAccess backend.

Run in an xrdp Linux desktop session where `DISPLAY` and rdAccess are configured:

```sh
python3 examples/xrdp/rdaccess_speak_test.py "Hello from Linux"
```

This is not part of the recommended NVDA Remote + Orca Remote installation. Avoid including sensitive speech text in shared logs.
