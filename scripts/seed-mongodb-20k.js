const seedCount = Number.parseInt(process.env.SEED_COUNT || "20000", 10);
const forceSeed = process.env.FORCE_SEED === "true";
const batchSize = 1000;
const prefix = "fake_seed_";
const passwordHash = "$2b$12$5RHTUV9lTrB4FG4pLeKZr.hJbaLC20XlD0UaIxN.Lo0Fx0FLnv8ty";

if (!Number.isInteger(seedCount) || seedCount < 20000) {
  throw new Error("SEED_COUNT must be an integer greater than or equal to 20000");
}

if (forceSeed) {
  db.users.deleteMany({ user_id: { $regex: "^fake_seed_" } });
}

for (let first = 1; first <= seedCount; first += batchSize) {
  const operations = [];
  const last = Math.min(first + batchSize - 1, seedCount);

  for (let number = first; number <= last; number += 1) {
    const sequence = number.toString().padStart(6, "0");
    const userId = `${prefix}${sequence}`;
    const createdAt = new Date(Date.UTC(2026, 0, 1 + (number % 365))).toISOString();

    operations.push({
      updateOne: {
        filter: { user_id: userId },
        update: {
          $setOnInsert: {
            user_id: userId,
            email: `${userId}@example.com`,
            password_hash: passwordHash,
            roles: ["customer"],
            preferences: {
              currency: number % 2 === 0 ? "PEN" : "USD",
              theme: number % 3 === 0 ? "light" : "dark",
            },
            created_at: createdAt,
            seed_version: "rubrica-20k-v1",
          },
        },
        upsert: true,
      },
    });
  }

  const result = db.users.bulkWrite(operations, { ordered: false });
  if (!result.acknowledged) {
    throw new Error(`MongoDB did not acknowledge batch starting at ${first}`);
  }
}

const fakeRows = db.users.countDocuments({ user_id: { $regex: "^fake_seed_" } });
if (fakeRows < seedCount) {
  throw new Error(`MongoDB only contains ${fakeRows} fake users; expected ${seedCount}`);
}

print(`OK database=mongodb collection=users fake_rows=${fakeRows} requested=${seedCount}`);
