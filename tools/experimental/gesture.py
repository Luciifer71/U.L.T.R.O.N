#!/usr/bin/env python3
"""gesture.py - Async MediaPipe hand tracker publishing gesture events to NATS."""
import os, math, time, json, asyncio, urllib.request
from pathlib import Path
import cv2
from datetime import datetime, timezone

MODEL_PATH = str(Path(__file__).resolve().parents[2] / "assets" / "models" / "hand_landmarker.task")
MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
NATS_URL = "nats://localhost:4222"
SUBJECT = "ultron.gestures"
DEVICE_ID = "laptop_01"
COOLDOWN = 1.5
TIP_IDS = [8, 12, 16, 20]
PIP_IDS = [6, 10, 14, 18]

def ensure_model():
    try:
        if not os.path.exists(MODEL_PATH):
            print("Downloading hand_landmarker.task ...")
            Path(MODEL_PATH).parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        return True
    except Exception as e:
        print(f"Model download failed: {e}")
        return False

def open_camera():
    for idx in (0, 1):
        cap = cv2.VideoCapture(idx)
        if cap.isOpened():
            print(f"Camera index {idx} opened.")
            return cap
        cap.release()
    print("ERROR: No camera available on index 0 or 1.")
    return None

def count_fingers(lm, w, h):
    pts = [(int(p.x * w), int(p.y * h)) for p in lm]
    count = sum(1 for tip, pip in zip(TIP_IDS, PIP_IDS) if pts[tip][1] < pts[pip][1])
    pb = pts[17]
    d_tip = math.hypot(pts[4][0] - pb[0], pts[4][1] - pb[1])
    d_ip = math.hypot(pts[3][0] - pb[0], pts[3][1] - pb[1])
    if d_tip > d_ip:
        count += 1
    return count, pts

async def publish_gesture(nc, name, last_sent):
    now = time.monotonic()
    if now - last_sent[0] < COOLDOWN:
        return
    last_sent[0] = now
    payload = {
        "device_id": DEVICE_ID,
        "gesture": name,
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    try:
        if nc is not None:
            await nc.publish(SUBJECT, json.dumps(payload).encode())
        print(f"[NATS PUBLISHED]: {name}")
    except Exception as e:
        print(f"NATS publish failed: {e}")

async def main():
    nc = None
    try:
        import nats
        nc = await nats.connect(NATS_URL)
        print("Connected to NATS.")
    except Exception as e:
        print(f"NATS connection failed, running offline: {e}")

    if not ensure_model():
        print("Cannot continue without model.")
        return
    import mediapipe as mp
    from mediapipe.tasks.python import vision, BaseOptions
    options = vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=MODEL_PATH), num_hands=1)
    landmarker = vision.HandLandmarker.create_from_options(options)

    cap = open_camera()
    if cap is None:
        if nc: await nc.close()
        return

    last_sent = [0.0]
    try:
        while True:
            try:
                ok, frame = cap.read()
                if not ok or frame is None:
                    await asyncio.sleep(0.01)
                    continue
                h, w = frame.shape[:2]
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
                result = landmarker.detect(mp_img)
                if result.hand_landmarks:
                    lm = result.hand_landmarks[0]
                    count, pts = count_fingers(lm, w, h)
                    for i, (x, y) in enumerate(pts):
                        cv2.circle(frame, (x, y), 6, (0, 255, 0), -1)
                    for a, b in [(0, 4), (0, 8), (0, 12), (0, 16), (0, 20)]:
                        cv2.line(frame, pts[a], pts[b], (0, 255, 0), 2)
                    if count == 0:
                        print("FIST DETECTED")
                        await publish_gesture(nc, "FIST DETECTED", last_sent)
                    elif count == 5:
                        print("PALM OPEN")
                        await publish_gesture(nc, "PALM OPEN", last_sent)
                    else:
                        print(f"{count} FINGERS DETECTED")
                cv2.imshow("Gesture Tracker", frame)
            except Exception as e:
                print(f"Frame error (skipped): {e}")

            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
            await asyncio.sleep(0)
    finally:
        cap.release()
        cv2.destroyAllWindows()
        if nc is not None:
            await nc.close()
            print("NATS connection closed.")

if __name__ == "__main__":
    asyncio.run(main())