#!/bin/sh
set -e

endpoint="${MINIO_ENDPOINT:-http://minio:9000}"
bucket="${QAP_S3_BUCKET:-qa-platform}"

mc alias set local "$endpoint" "${MINIO_ROOT_USER:-minioadmin}" "${MINIO_ROOT_PASSWORD:-minioadmin}"
mc mb --ignore-existing "local/${bucket}"
