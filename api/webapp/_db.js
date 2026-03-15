/**
 * api/webapp/_db.js
 * -----------------
 * Shared MongoDB connection for all webapp API routes.
 *
 * WHY A SHARED MODULE:
 * Each Vercel serverless function is a separate Node.js process, but on warm
 * invocations the module cache is reused.  By caching the MongoClient promise
 * here, we get connection pooling across warm requests — the same optimisation
 * your Python bot gets from Motor's connection pool.
 *
 * The leading underscore in the filename tells Vercel NOT to treat this file
 * as a standalone API route endpoint.
 */

const { MongoClient } = require("mongodb");

const MONGO_URL = process.env.MONGO_URL;
const DB_NAME   = "MenzumaDB";

if (!MONGO_URL) {
  throw new Error("MONGO_URL environment variable is not set.");
}

// Module-level cache: reused across warm invocations on the same Vercel instance
let cachedClient = null;
let cachedDb     = null;

async function connectToDatabase() {
  // Return cached connection if available and still connected
  if (cachedClient && cachedDb) {
    return { client: cachedClient, db: cachedDb };
  }

  const client = new MongoClient(MONGO_URL, {
    // Keep connection alive between serverless invocations
    maxPoolSize:      10,
    serverSelectionTimeoutMS: 5000,
    socketTimeoutMS:          10000,
  });

  await client.connect();
  const db = client.db(DB_NAME);

  cachedClient = client;
  cachedDb     = db;

  return { client, db };
}

module.exports = { connectToDatabase };
