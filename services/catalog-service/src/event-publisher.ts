import { PutObjectCommand, S3Client } from "@aws-sdk/client-s3";

import { buildEventKey, DomainEvent, serializeEvent } from "./events";

function createS3Client(): S3Client {
  const endpoint = process.env.S3_ENDPOINT_URL;
  return new S3Client({
    region: process.env.AWS_DEFAULT_REGION ?? "us-east-1",
    endpoint,
    forcePathStyle: Boolean(endpoint),
  });
}

export async function publishEvent(event: DomainEvent): Promise<string | null> {
  const key = buildEventKey(
    process.env.S3_EVENTS_PREFIX ?? "raw/events/catalog/",
    event
  );

  try {
    await createS3Client().send(
      new PutObjectCommand({
        Bucket: process.env.S3_BUCKET ?? "hardtech-datalake",
        Key: key,
        Body: serializeEvent(event),
        ContentType: "application/json",
      })
    );
    return key;
  } catch (error) {
    console.error(
      `Business operation completed, but ${event.event_type} could not be written to S3`,
      error
    );
    return null;
  }
}
