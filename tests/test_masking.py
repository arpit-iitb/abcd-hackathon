from app.core.masking import mask_aadhaar, mask_pan, mask_sensitive


def test_mask_pan():
    assert mask_pan("ABCDE1234F").endswith("1234")
    assert "ABCDE" not in mask_pan("ABCDE1234F")


def test_mask_aadhaar():
    assert mask_aadhaar("123412341234").endswith("1234")
    assert "12341234" not in mask_aadhaar("123412341234")


def test_mask_sensitive_dict():
    payload = {"pan": "ABCDE1234F", "aadhaar": "123412341234"}
    masked = mask_sensitive(payload)
    assert masked["pan"] != payload["pan"]
    assert masked["aadhaar"] != payload["aadhaar"]
