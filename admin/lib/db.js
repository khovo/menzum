/**
 * lib/db.js
 * ---------
 * Shared MongoDB connection for the admin app's API routes.
 * Mirrors the pattern in the bot project's api/webapp/_db.js: cache the
 * MongoClient at module scope so warm serverless invocations reuse the pool.
 *
 * Same database (MenzumaDB) as the bot and the Mini App — this admin panel
 * reads/writes the exact same `files`, `pdfs`, `users`, `banned_users`
 * collections the bot already uses.
 */
const { MongoClient } = require("mongodb");

const MONGO_URL = process.env.MONGO_URL;
const DB_NAME = "MenzumaDB";

let cachedClient = null;
let cachedDb = null;

async function connectToDatabase() {
  if (!MONGO_URL) {
    throw new Error("MONGO_URL environment variable is not set.");
  }
  if (cachedClient && cachedDb) {
    return { client: cachedClient, db: cachedDb };
  }

  const client = new MongoClient(MONGO_URL, {
    maxPoolSize: 10,
    serverSelectionTimeoutMS: 5000,
    socketTimeoutMS: 10000,
  });

  await client.connect();
  const db = client.db(DB_NAME);

  cachedClient = client;
  cachedDb = db;

  return { client, db };
}

module.exports = { connectToDatabase };
