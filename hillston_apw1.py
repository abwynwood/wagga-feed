from pathlib import Path
from cropconnect_grain import update

update("Hillston", "APW1", "hillston_apw1.xml")
path = Path("hillston_apw1.xml")
text = path.read_text(encoding="utf-8")
path.write_text(text.replace("<br>Trend: building 7-day history", ""), encoding="utf-8")
