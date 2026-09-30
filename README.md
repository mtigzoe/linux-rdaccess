# linux-rdaccess

python3 -m unittest discover -s tests -t .
python3 -m py_compile *.py diagnostics/*.py tests/*.py
DISPLAY=:10 python3 atspi_nvda_bridge.py --debug
python3 atspi_nvda_bridge.py --dry-run --debug
DISPLAY=:10 python3 atspi_nvda_bridge.py --debug
