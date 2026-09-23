const identityDb = db.getSiblingDB("hardtech_identity");
const appUser = process.env.MONGO_APP_USER || "hardtech";
const appPassword = process.env.MONGO_APP_PASSWORD || "hardtech";
const readerUser = process.env.MONGO_READER_USER || "hardtech_reader";
const readerPassword = process.env.MONGO_READER_PASSWORD || "hardtech_reader";

if (!identityDb.getUser(appUser)) {
  identityDb.createUser({
    user: appUser,
    pwd: appPassword,
    roles: [{ role: "readWrite", db: "hardtech_identity" }],
  });
} else {
  identityDb.updateUser(appUser, {
    pwd: appPassword,
    roles: [{ role: "readWrite", db: "hardtech_identity" }],
  });
}

if (!identityDb.getUser(readerUser)) {
  identityDb.createUser({
    user: readerUser,
    pwd: readerPassword,
    roles: [{ role: "read", db: "hardtech_identity" }],
  });
} else {
  identityDb.updateUser(readerUser, {
    pwd: readerPassword,
    roles: [{ role: "read", db: "hardtech_identity" }],
  });
}

const users = identityDb.getCollection("users");
users.createIndex({ user_id: 1 }, { unique: true, name: "user_id_unique" });
users.createIndex({ email: 1 }, { unique: true, name: "email_unique" });

users.updateOne(
  { user_id: "usr_demo_001" },
  {
    $setOnInsert: {
      user_id: "usr_demo_001",
      email: "demo@hardtech.com",
      password_hash: "$2b$12$5RHTUV9lTrB4FG4pLeKZr.hJbaLC20XlD0UaIxN.Lo0Fx0FLnv8ty",
      roles: ["customer"],
      preferences: { currency: "PEN", theme: "dark" },
      created_at: "2026-09-02T10:00:00Z",
    },
  },
  { upsert: true }
);
