#!/bin/bash
set -euo pipefail

echo "Creating S3 bucket in LocalStack..."

awslocal s3 mb s3://hardtech-datalake || true

echo "LocalStack bootstrap complete."
