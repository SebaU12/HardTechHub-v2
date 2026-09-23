import logging
import os
import socket
from datetime import datetime, timedelta, timezone
from typing import Any

import boto3
import jwt
import bcrypt
from botocore.exceptions import BotoCoreError, ClientError
from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, EmailStr
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.errors import DuplicateKeyError, PyMongoError

from app.events import build_event, build_event_key, serialize_event


log = logging.getLogger("identity-service")


def get_mongo_client() -> MongoClient:
    return MongoClient(
        os.getenv(
            "MONGODB_URI",
            "mongodb://hardtech:hardtech@mongodb:27017/hardtech_identity?authSource=hardtech_identity",
        ),
        serverSelectionTimeoutMS=int(os.getenv("MONGODB_TIMEOUT_MS", "5000")),
    )


def _servers() -> list[dict[str, str]]:
    base = os.getenv("API_BASE_URL", "").strip()
    return [{"url": base, "description": "API Gateway / Local"}] if base else []


app = FastAPI(
    title="Identity Service",
    version="1.0.0",
    docs_url="/identity/docs",
    openapi_url="/identity/openapi.json",
    servers=_servers(),
)


def get_users_collection() -> Collection:
    database = get_mongo_client()[os.getenv("MONGODB_DATABASE", "hardtech_identity")]
    return database[os.getenv("MONGODB_USERS_COLLECTION", "users")]


def get_s3_client() -> Any:
    kwargs: dict[str, Any] = {
        "region_name": os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    }
    if endpoint := os.getenv("S3_ENDPOINT_URL"):
        kwargs["endpoint_url"] = endpoint
    if access_key := os.getenv("AWS_ACCESS_KEY_ID"):
        kwargs["aws_access_key_id"] = access_key
    if secret_key := os.getenv("AWS_SECRET_ACCESS_KEY"):
        kwargs["aws_secret_access_key"] = secret_key
    return boto3.client("s3", **kwargs)


def build_user_registered_event(item: dict[str, Any]) -> dict[str, Any]:
    preferences = item.get("preferences", {})
    return build_event(
        event_type="USER_REGISTERED",
        source="identity-service",
        user_id=item["user_id"],
        payload={
            "roles": item.get("roles", []),
            "currency": preferences.get("currency"),
            "theme": preferences.get("theme"),
            "registered_at": item["created_at"],
        },
    )


def publish_user_registered_event(item: dict[str, Any]) -> str | None:
    event = build_user_registered_event(item)
    key = build_event_key(os.getenv("S3_EVENTS_PREFIX", "raw/events/identity/"), event)
    try:
        get_s3_client().put_object(
            Bucket=os.getenv("S3_BUCKET", "hardtech-datalake"),
            Key=key,
            Body=serialize_event(event),
            ContentType="application/json",
        )
    except (BotoCoreError, ClientError) as exc:
        log.error("User %s was registered, but USER_REGISTERED could not be written to S3: %s",
                  item["user_id"], exc)
        return None

    log.info("Published USER_REGISTERED at s3://%s/%s",
             os.getenv("S3_BUCKET", "hardtech-datalake"), key)
    return key


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


def get_jwt_secret() -> str:
    return os.getenv("JWT_SECRET", "hardtech-dev-secret")


def get_jwt_expiration_minutes() -> int:
    return int(os.getenv("JWT_EXP_MINUTES", "60"))


def hash_password(password: str) -> str:
    password_bytes = password.encode("utf-8")
    return bcrypt.hashpw(password_bytes, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), password_hash.encode("utf-8"))


def build_access_token(user_id: str, email: str, roles: list[str]) -> str:
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=get_jwt_expiration_minutes())
    payload = {
        "sub": user_id,
        "email": email,
        "roles": roles,
        "exp": expires_at,
    }
    return jwt.encode(payload, get_jwt_secret(), algorithm="HS256")


def normalize_roles(raw_roles: Any) -> list[str]:
    if not raw_roles:
        return []
    return [role for role in raw_roles if isinstance(role, str)]


def decode_bearer_token(authorization: str | None) -> dict[str, Any]:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")

    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Invalid Authorization header")

    try:
        return jwt.decode(token, get_jwt_secret(), algorithms=["HS256"])
    except jwt.ExpiredSignatureError as exc:
        raise HTTPException(status_code=401, detail="Token expired") from exc
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


@app.get("/health")
def healthcheck() -> dict[str, str]:
    return {
        "service": "identity-service",
        "status": "healthy",
        "version": "1.0.0",
        "instance": os.getenv("INSTANCE_ID", socket.gethostname()),
    }


@app.post("/api/auth/register")
def register(payload: RegisterRequest) -> dict[str, Any]:
    users = get_users_collection()
    email = str(payload.email)
    user_id = email.split("@")[0]
    item = {
        "user_id": user_id,
        "email": email,
        "password_hash": hash_password(payload.password),
        "roles": ["customer"],
        "preferences": {"currency": "PEN", "theme": "dark"},
        "created_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        users.insert_one(item)
    except DuplicateKeyError as exc:
        raise HTTPException(status_code=400, detail="User already exists") from exc
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="MongoDB error") from exc

    event_key = publish_user_registered_event(item)
    return {
        "message": "User registered",
        "user_id": user_id,
        "event_published": event_key is not None,
        "event_key": event_key,
    }


@app.post("/api/auth/login")
def login(payload: LoginRequest) -> dict[str, str]:
    try:
        matched_user = get_users_collection().find_one({"email": str(payload.email)})
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="MongoDB error") from exc

    if not matched_user:
        raise HTTPException(status_code=401, detail="Invalid credentials")

    stored_hash = matched_user.get("password_hash", "")
    if not verify_password(payload.password, stored_hash):
        raise HTTPException(status_code=401, detail="Invalid credentials")

    roles = normalize_roles(matched_user.get("roles", []))

    return {
        "access_token": build_access_token(matched_user["user_id"], matched_user["email"], roles),
        "token_type": "bearer",
    }


@app.get("/api/auth/me")
def get_authenticated_user(authorization: str | None = Header(default=None)) -> dict[str, Any]:
    payload = decode_bearer_token(authorization)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token payload")

    try:
        item = get_users_collection().find_one({"user_id": user_id})
    except PyMongoError as exc:
        raise HTTPException(status_code=500, detail="MongoDB error") from exc

    if not item:
        raise HTTPException(status_code=404, detail="User not found")

    return {
        "user_id": item.get("user_id"),
        "email": item.get("email"),
        "roles": normalize_roles(item.get("roles", [])),
        "preferences": item.get("preferences", {}),
        "created_at": item.get("created_at"),
    }
