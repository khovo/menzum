import os
import json
import asyncio
import aiohttp
from http.server import BaseHTTPRequestHandler
from motor.motor_asyncio import AsyncIOMotorClient

BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")
DB_NAME = "MenzumaDB"
CRON_SECRET = os.environ.get("CRON_SECRET") # Optional Vercel Cron Secret

async def process_broadcast_chunk():
    if not BOT_TOKEN or not MONGO_URL:
        return {"status": "error", "message": "Missing environment variables"}

    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    try:
        # Find one pending or processing job
        job = await db.broadcast_queue.find_one_and_update(
            {"status": {"$in": ["pending", "processing"]}},
            {"$set": {"status": "processing"}},
            sort=[("created_at", 1)]
        )

        if not job:
            return {"status": "ok", "message": "No active broadcasts in queue"}

        job_id = job["_id"]
        admin_chat_id = job["admin_chat_id"]
        msg_id = job["msg_id"]
        reply_markup = job.get("reply_markup")
        recipients = job.get("recipient_ids", [])
        last_idx = job.get("last_processed_index", 0)

        chunk_size = 30
        end_idx = min(last_idx + chunk_size, len(recipients))
        chunk_recipients = recipients[last_idx:end_idx]

        sent_count = 0
        failed_count = 0

        async with aiohttp.ClientSession() as session:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/copyMessage"
            
            for uid in chunk_recipients:
                payload = {
                    "chat_id": uid,
                    "from_chat_id": admin_chat_id,
                    "message_id": msg_id
                }
                if reply_markup:
                    payload["reply_markup"] = reply_markup

                try:
                    async with session.post(url, json=payload) as resp:
                        res_data = await resp.json()
                        if res_data.get("ok"):
                            sent_count += 1
                        else:
                            failed_count += 1
                except Exception:
                    failed_count += 1
                
                # ~0.04s sleep enforces the 30 msg/sec rate limit.
                # Total loop takes ~1.2s, safely under Vercel's 10s strict limit.
                await asyncio.sleep(0.04)

        # Update Database Stats
        is_completed = end_idx >= len(recipients)
        new_status = "completed" if is_completed else "processing"

        await db.broadcast_queue.update_one(
            {"_id": job_id},
            {
                "$inc": {"sent_count": sent_count, "failed_count": failed_count},
                "$set": {"last_processed_index": end_idx, "status": new_status}
            }
        )

        # Notify Admin if completed
        if is_completed:
            final_job = await db.broadcast_queue.find_one({"_id": job_id})
            async with aiohttp.ClientSession() as session:
                notify_url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
                summary_msg = (
                    "✅ *Broadcast Complete*\n\n"
                    f"📤 Delivered: {final_job.get('sent_count', 0)}\n"
                    f"❌ Failed: {final_job.get('failed_count', 0)}"
                )
                await session.post(notify_url, json={"chat_id": admin_chat_id, "text": summary_msg, "parse_mode": "Markdown"})

        return {"status": "ok", "processed": len(chunk_recipients), "is_completed": is_completed}

    finally:
        client.close()

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        # Optional Security Check: Validate Cron Request
        auth_header = self.headers.get('Authorization')
        if CRON_SECRET and auth_header != f"Bearer {CRON_SECRET}":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b"Unauthorized")
            return

        result = asyncio.run(process_broadcast_chunk())
        
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(result).encode('utf-8'))

