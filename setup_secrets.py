"""
Sla de API-keys éénmalig op in Windows Credential Manager.
Run dit script één keer:  python setup_secrets.py
"""

import keyring
import getpass

print("=== Secrets opslaan in Windows Credential Manager ===\n")

solar_key = getpass.getpass("Solar AUTH_key (solarlogs.be meter API): ")
keyring.set_password("V1Eindwerk", "solar_auth_key", solar_key)
print("✓ solar_auth_key opgeslagen")

battery_key = getpass.getpass("Battery AUTH_key (solarlogs.be ilucharge API): ")
keyring.set_password("V1Eindwerk", "battery_auth_key", battery_key)
print("✓ battery_auth_key opgeslagen")

print("\nKlaar. Je kan dit script verwijderen.")
