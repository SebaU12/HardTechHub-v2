const identityDb = db.getSiblingDB("hardtech_identity");

if (!identityDb.getUser("hardtech")) {
  identityDb.createUser({
    user: "hardtech",
    pwd: "hardtech",
    roles: [{ role: "readWrite", db: "hardtech_identity" }],
  });
}

if (!identityDb.getUser("hardtech_reader")) {
  identityDb.createUser({
    user: "hardtech_reader",
    pwd: "hardtech_reader",
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
