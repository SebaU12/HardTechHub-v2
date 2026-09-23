package main

import (
	"bytes"
	"context"
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	"github.com/aws/aws-sdk-go-v2/config"
	"github.com/aws/aws-sdk-go-v2/service/s3"
)

type DomainEvent struct {
	EventID   string                 `json:"event_id"`
	EventType string                 `json:"event_type"`
	Timestamp string                 `json:"timestamp"`
	Source    string                 `json:"source"`
	UserID    *string                `json:"user_id"`
	SessionID *string                `json:"session_id"`
	ProductID *int                   `json:"product_id"`
	OrderID   *int                   `json:"order_id"`
	Payload   map[string]interface{} `json:"payload"`
}

func newEventID() (string, error) {
	randomBytes := make([]byte, 4)
	if _, err := rand.Read(randomBytes); err != nil {
		return "", err
	}
	return "evt_" + hex.EncodeToString(randomBytes), nil
}

func buildEvent(eventType string, source string, payload map[string]interface{}) (DomainEvent, error) {
	eventID, err := newEventID()
	if err != nil {
		return DomainEvent{}, err
	}
	return DomainEvent{
		EventID:   eventID,
		EventType: eventType,
		Timestamp: time.Now().UTC().Format("2006-01-02T15:04:05Z"),
		Source:    source,
		Payload:   payload,
	}, nil
}

func buildEventKey(prefix string, event DomainEvent) (string, error) {
	timestamp, err := time.Parse("2006-01-02T15:04:05Z", event.Timestamp)
	if err != nil {
		return "", err
	}
	normalizedPrefix := strings.Trim(prefix, "/")
	filename := fmt.Sprintf("%s_%s.json", strings.ToLower(event.EventType), event.EventID)
	return fmt.Sprintf(
		"%s/year=%04d/month=%02d/day=%02d/%s",
		normalizedPrefix,
		timestamp.Year(),
		int(timestamp.Month()),
		timestamp.Day(),
		filename,
	), nil
}

func serializeEvent(event DomainEvent) ([]byte, error) {
	return json.Marshal(event)
}

func publishEvent(ctx context.Context, event DomainEvent) (string, error) {
	key, err := buildEventKey(envOrDefault("S3_EVENTS_PREFIX", "raw/events/compatibility/"), event)
	if err != nil {
		return "", err
	}
	body, err := serializeEvent(event)
	if err != nil {
		return "", err
	}

	cfg, err := config.LoadDefaultConfig(
		ctx,
		config.WithRegion(envOrDefault("AWS_DEFAULT_REGION", "us-east-1")),
	)
	if err != nil {
		return "", err
	}
	endpoint := os.Getenv("S3_ENDPOINT_URL")
	client := s3.NewFromConfig(cfg, func(options *s3.Options) {
		if endpoint != "" {
			options.BaseEndpoint = aws.String(endpoint)
			options.UsePathStyle = true
		}
	})
	_, err = client.PutObject(ctx, &s3.PutObjectInput{
		Bucket:      aws.String(envOrDefault("S3_BUCKET", "hardtech-datalake")),
		Key:         aws.String(key),
		Body:        bytes.NewReader(body),
		ContentType: aws.String("application/json"),
	})
	if err != nil {
		return "", err
	}
	return key, nil
}

func envOrDefault(name string, fallback string) string {
	if value := os.Getenv(name); value != "" {
		return value
	}
	return fallback
}
