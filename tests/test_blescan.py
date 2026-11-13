"""Tests for the BLE scanner/classifier (Phase 6 #8)."""
import blescan


def test_oui_vendor_lookup():
    assert blescan.oui_vendor("B8:27:EB:11:22:33") == "Raspberry Pi"
    assert blescan.oui_vendor("60:60:1F:aa:bb:cc") == "DJI"
    assert blescan.oui_vendor("FF:FF:FF:00:00:00") is None


def test_classify_odid_drone():
    adv = {"address": "AA:BB:CC:DD:EE:FF", "rssi": -60, "name": "",
           "service_uuids": ["0000fffa-0000-1000-8000-00805f9b34fb"]}
    d = blescan.classify_advert(adv)
    assert d["is_odid"] is True and "drone-remoteid" in d["tags"]


def test_classify_plain_device():
    adv = {"address": "B8:27:EB:01:02:03", "rssi": -40, "name": "pi-sensor",
           "service_uuids": ["0000180f-0000-1000-8000-00805f9b34fb"]}
    d = blescan.classify_advert(adv)
    assert d["is_odid"] is False and d["vendor"] == "Raspberry Pi" and d["name"] == "pi-sensor"


def test_apple_manufacturer_tag():
    adv = {"address": "AC:BC:32:00:00:01", "rssi": -50, "manufacturer_data": {0x004C: b"\x02\x15"}}
    d = blescan.classify_advert(adv)
    assert "apple" in d["tags"] and d["vendor"] == "Apple"


def test_devices_model_and_drone_filter():
    dev = blescan.Devices()
    dev.ingest({"address": "AA:01", "rssi": -60,
                "service_uuids": ["0000fffa-0000-1000-8000-00805f9b34fb"]}, now=1)
    dev.ingest({"address": "AA:02", "rssi": -40, "name": "watch"}, now=2)
    assert len(dev.active(now=2)) == 2
    assert [d["address"] for d in dev.drones(now=2)] == ["AA:01"]
