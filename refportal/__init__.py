"""A reference SAHYOG portal: a small separate program that implements the portal's half
of docs/sahyog_contract.md, so the tool's HTTP integration can be run and tested end to
end. It is not the SAHYOG portal and copies nothing of it: the real portal's interface
is not public. It shares no code with the tool (`vaspfusion/`), only the contract.

    python -m refportal --port 8100 --tool http://127.0.0.1:8000
"""
NOTICE = "A simulator for demonstration. Not the SAHYOG portal."
