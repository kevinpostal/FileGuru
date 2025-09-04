from google.cloud import storage
import os

os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = "/home/kpostal/yt-dlp-worker-key.json"

# Test storage access
storage_client = storage.Client()
buckets = list(storage_client.list_buckets())
print(f"Buckets: {[b.name for b in buckets]}")

# Test Pub/Sub access
from google.cloud import pubsub_v1
subscriber = pubsub_v1.SubscriberClient()
subscription_path = subscriber.subscription_path("hosting-shit", "yt-dlp-downloads-sub")
print(f"Subscription path: {subscription_path}")
