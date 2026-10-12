#!/bin/bash
cd -- "$(dirname -- "$0")" || exit 1
for td_python in python3 /usr/local/bin/python3 /opt/homebrew/bin/python3 /Library/Frameworks/Python.framework/Versions/Current/bin/python3; do
  if "$td_python" -c 'import sys; raise SystemExit(sys.version_info < (3, 9))' 2>/dev/null; then
    "$td_python" start_browser.py
    td_result=$?
    if [ "$td_result" -ne 0 ]; then
      read -r -p "Zum Schließen die Eingabetaste drücken. "
    fi
    exit "$td_result"
  fi
done
echo "Python 3.9 oder neuer wurde auf diesem Mac nicht gefunden."
echo "Dieser Browser-Start benötigt eine vorhandene Python-Installation."
read -r -p "Zum Schließen die Eingabetaste drücken. "
exit 1
