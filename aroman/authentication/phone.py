import re
import unicodedata


def normalize_mobile(value: str) -> str:
    digits = "".join(str(unicodedata.digit(char)) if char.isdigit() else char for char in value)
    digits = re.sub(r"[\s\-()]+", "", digits)
    if digits.startswith("0098"):
        digits = "+98" + digits[4:]
    elif digits.startswith("98"):
        digits = "+98" + digits[2:]
    elif digits.startswith("0"):
        digits = "+98" + digits[1:]
    if not re.fullmatch(r"\+989\d{9}", digits):
        raise ValueError("Invalid Iranian mobile number")
    return digits
