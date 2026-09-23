package main

import (
	"encoding/json"
	"regexp"
	"testing"
)

func TestBuildEventCreatesCommonEnvelope(t *testing.T) {
	event, err := buildEvent("COMPATIBILITY_CHECKED", "compatibility-service", map[string]interface{}{"compatible": true})
	if err != nil {
		t.Fatalf("buildEvent returned error: %v", err)
	}
	if !regexp.MustCompile(`^evt_[0-9a-f]{8}$`).MatchString(event.EventID) {
		t.Fatalf("unexpected event id: %s", event.EventID)
	}
	if event.EventType != "COMPATIBILITY_CHECKED" || event.Source != "compatibility-service" {
		t.Fatalf("unexpected envelope: %+v", event)
	}
}

func TestBuildEventKeyAndSerialization(t *testing.T) {
	event := DomainEvent{
		EventID:   "evt_1234abcd",
		EventType: "COMPATIBILITY_CHECKED",
		Timestamp: "2026-09-23T15:30:00Z",
		Source:    "compatibility-service",
		Payload:   map[string]interface{}{"compatible": false},
	}
	key, err := buildEventKey("/raw/events/compatibility/", event)
	if err != nil {
		t.Fatalf("buildEventKey returned error: %v", err)
	}
	expected := "raw/events/compatibility/year=2026/month=09/day=23/compatibility_checked_evt_1234abcd.json"
	if key != expected {
		t.Fatalf("expected %s, got %s", expected, key)
	}
	body, err := serializeEvent(event)
	if err != nil {
		t.Fatalf("serializeEvent returned error: %v", err)
	}
	var decoded DomainEvent
	if err := json.Unmarshal(body, &decoded); err != nil {
		t.Fatalf("serialized event is invalid JSON: %v", err)
	}
	if decoded.EventID != event.EventID {
		t.Fatalf("expected event id %s, got %s", event.EventID, decoded.EventID)
	}
}
