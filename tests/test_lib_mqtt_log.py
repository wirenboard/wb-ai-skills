"""Tests for ``wb_cli.lib.mqtt_log``."""

from __future__ import annotations

from wb_cli.lib import mqtt_log


def test_parse_publish_basic():
    line = (
        "1778654671: Received PUBLISH from wb-adc "
        "(d0, q1, r1, m53258, '/devices/wb-adc/controls/V5_0', ... (5 bytes))"
    )
    entry = mqtt_log.parse_publish(line)
    assert entry == {
        "source": "wb-adc",
        "dup": False,
        "qos": 1,
        "retain": True,
        "message_id": 53258,
        "topic": "/devices/wb-adc/controls/V5_0",
        "payload_size": 5,
    }


def test_parse_publish_wb_rules_source():
    """wb-rules uses a long client id with double-underscores."""
    line = (
        "Received PUBLISH from system__wb-rules__cAbCdEfGhIjK "
        "(d0, q0, r0, m1234, '/devices/wb-mr6c_7/controls/K1/on', ... (1 bytes))"
    )
    entry = mqtt_log.parse_publish(line)
    assert entry is not None
    assert entry["source"] == "system__wb-rules__cAbCdEfGhIjK"
    assert entry["qos"] == 0
    assert entry["retain"] is False


def test_parse_publish_topic_with_spaces():
    """WB controls often have spaces in the name; mosquitto quotes the topic."""
    line = (
        "Received PUBLISH from wb-mqtt-homeui-xyz "
        "(d0, q0, r0, m9, '/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/on', ... (2 bytes))"
    )
    entry = mqtt_log.parse_publish(line)
    assert entry is not None
    assert entry["topic"] == "/devices/wb-mdm3_5/controls/Channel 1 Dimming Level/on"


def test_parse_publish_ignores_non_publish():
    """Other mosquitto log lines must return None — not a PUBLISH."""
    assert mqtt_log.parse_publish("Client wb-adc connected") is None
    assert mqtt_log.parse_publish("New connection from 127.0.0.1") is None
    assert mqtt_log.parse_publish("") is None
    sending_line = "1778654671: Sending PUBLISH to wb-adc (d0, q1, r0, m99, '/devices/x/y', ... (1 bytes))"
    assert mqtt_log.parse_publish(sending_line) is None


def test_parse_entries_filters_by_topic_substring():
    journal = [
        {
            "__REALTIME_TIMESTAMP": "1778654671000000",
            "MESSAGE": "Received PUBLISH from wb-adc (d0, q1, r1, m1, "
            "'/devices/wb-adc/controls/V5_0', ... (5 bytes))",
        },
        {
            "__REALTIME_TIMESTAMP": "1778654672000000",
            "MESSAGE": "Received PUBLISH from wb-rules (d0, q0, r0, m2, "
            "'/devices/wb-mr6c_7/controls/K1/on', ... (1 bytes))",
        },
        {"__REALTIME_TIMESTAMP": "1778654673000000", "MESSAGE": "noise that is not a publish"},
    ]
    entries = mqtt_log.parse_entries(journal, topic="wb-mr6c_7")
    assert len(entries) == 1
    assert entries[0]["topic"] == "/devices/wb-mr6c_7/controls/K1/on"
    assert entries[0]["source"] == "wb-rules"
    assert entries[0]["timestamp"].startswith("2026")


def test_parse_entries_filters_by_source_substring():
    journal = [
        {
            "__REALTIME_TIMESTAMP": "1778654671000000",
            "MESSAGE": "Received PUBLISH from system__wb-rules__abc (d0, q0, r0, m1, "
            "'/devices/a/controls/x/on', ... (1 bytes))",
        },
        {
            "__REALTIME_TIMESTAMP": "1778654672000000",
            "MESSAGE": "Received PUBLISH from wb-mqtt-homeui-zzz (d0, q0, r0, m2, "
            "'/devices/a/controls/y/on', ... (1 bytes))",
        },
    ]
    entries = mqtt_log.parse_entries(journal, source="wb-rules")
    assert len(entries) == 1
    assert entries[0]["source"].startswith("system__wb-rules__")


def test_parse_entries_handles_missing_timestamp():
    """Some journal entries may not have __REALTIME_TIMESTAMP — leave it None."""
    journal = [
        {
            "MESSAGE": "Received PUBLISH from wb-adc (d0, q1, r0, m1, " "'/devices/x/y', ... (3 bytes))",
        }
    ]
    entries = mqtt_log.parse_entries(journal)
    assert len(entries) == 1
    assert entries[0]["timestamp"] is None
