import asyncio
import datetime
import json
import os
import random
import sys
import time
import websockets


class WasteSortingSimulator:
    """Async simulator for a tabletop/industrial smart waste sorting conveyor."""

    def __init__(self):
        self.running = False
        self.belt_speed = 0.6  # m/s
        self.spawn_interval = 3.0  # seconds between waste items
        self.waste_classes = [
            "cardboard",
            "glass",
            "metal",
            "paper",
            "plastic",
            "trash",
        ]
        self.waste_weights = [0.2, 0.1, 0.15, 0.25, 0.15, 0.15]
        self.bin_positions = {
            "cardboard": 1.5,
            "glass": 3.0,
            "metal": 4.5,
            "paper": 6.0,
            "plastic": 7.5,
            "trash": 9.0,
        }
        self.conveyor_length = 10.0  # meters
        self.detection_accuracy = 0.92  # 92% chance of correct classification
        self.total_sorted = 0
        self.stats = {cls: 0 for cls in self.waste_classes}
        self._item_counter = 0

    async def spawn_waste(self):
        """Spawn a single simulated waste object at the start of the conveyor."""
        self._item_counter += 1
        true_class = random.choices(
            self.waste_classes, weights=self.waste_weights, k=1
        )[0]
        return {
            "id": self._item_counter,
            "true_class": true_class,
            "spawn_time": time.time(),
            "x_position": 0.0,
        }

    async def classify_waste(self, waste_item):
        """Simulate AI waste classification (~92% accuracy) with realistic confidence."""
        true_class = waste_item["true_class"]
        if random.random() <= self.detection_accuracy:
            detected_class = true_class
            confidence = round(random.uniform(0.75, 0.99), 4)
        else:
            wrong_choices = [c for c in self.waste_classes if c != true_class]
            detected_class = random.choice(wrong_choices)
            confidence = round(random.uniform(0.40, 0.75), 4)

        return {
            "detected_class": detected_class,
            "confidence": confidence,
            "true_class": true_class,
        }

    async def run_sorting_cycle(self, ws_url="ws://localhost:8000/ws"):
        """Connect to the backend WebSocket and continuously stream sorting events."""
        while self.running:
            try:
                async with websockets.connect(ws_url) as ws:
                    print(f"Simulator connected to {ws_url}")
                    # Drain initial server init message if sent immediately
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        pass

                    while self.running:
                        # a. Spawn waste item
                        waste_item = await self.spawn_waste()

                        # b. Send spawn event
                        await ws.send(
                            json.dumps({"type": "spawn", "waste": waste_item})
                        )

                        # c. Wait for object to travel to camera zone
                        camera_wait = min(self.spawn_interval, 1.0 / max(self.belt_speed, 0.1))
                        await asyncio.sleep(camera_wait)
                        if not self.running:
                            break

                        # d. Classify waste
                        classification = await self.classify_waste(waste_item)
                        detected_class = classification["detected_class"]
                        confidence = classification["confidence"]
                        true_class = classification["true_class"]

                        # e. Determine target bin
                        assigned_bin = detected_class

                        # f. Send detection event
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "detection",
                                    "class": detected_class,
                                    "confidence": confidence,
                                }
                            )
                        )

                        # g. Wait gate travel time
                        gate_pos = self.bin_positions.get(assigned_bin, 4.5)
                        gate_travel_time = min(
                            gate_pos / max(self.belt_speed, 0.1),
                            self.spawn_interval,
                        )
                        await asyncio.sleep(gate_travel_time)
                        if not self.running:
                            break

                        # h. Determine sorting success
                        success = detected_class == true_class

                        # i. Send sorted event
                        await ws.send(
                            json.dumps(
                                {
                                    "type": "sorted",
                                    "class": detected_class,
                                    "confidence": confidence,
                                    "bin": assigned_bin,
                                    "success": success,
                                }
                            )
                        )

                        # j. Update local stats
                        self.total_sorted += 1
                        self.stats[detected_class] = self.stats.get(detected_class, 0) + 1
                        print(
                            f"[Sim #{self.total_sorted}] true={true_class} "
                            f"pred={detected_class} ({confidence:.2%}) "
                            f"bin={assigned_bin} success={success}"
                        )

                        # k. Sleep before spawning next waste item
                        await asyncio.sleep(self.spawn_interval)

            except (ConnectionRefusedError, OSError, websockets.WebSocketException) as e:
                if not self.running:
                    break
                print(f"WebSocket connection lost/unavailable ({e}). Retrying in 3s...")
                await asyncio.sleep(3.0)

    async def start(self, ws_url="ws://localhost:8000/ws"):
        """Start the simulator loop."""
        self.running = True
        await self.run_sorting_cycle(ws_url=ws_url)

    def stop(self):
        """Signal the simulator loop to stop gracefully."""
        self.running = False


async def start_simulation_task(manager, db_module, is_running_fn=None):
    """Run the waste sorting simulator inside the FastAPI server process."""
    sim = WasteSortingSimulator()
    sim.running = True

    def _keep_running():
        return is_running_fn() if is_running_fn is not None else sim.running

    while _keep_running():
        waste_item = await sim.spawn_waste()
        await manager.broadcast({"type": "spawn", "data": waste_item})

        classification = await sim.classify_waste(waste_item)
        detected_class = classification["detected_class"]
        confidence = classification["confidence"]
        true_class = classification["true_class"]
        assigned_bin = detected_class
        success = detected_class == true_class

        event_id = await asyncio.to_thread(
            db_module.add_sort_event,
            detected_class,
            confidence,
            assigned_bin,
            success,
        )

        await manager.broadcast(
            {
                "type": "sort_event",
                "data": {
                    "id": event_id,
                    "detected_class": detected_class,
                    "confidence": confidence,
                    "assigned_bin": assigned_bin,
                    "success": success,
                    "timestamp": datetime.datetime.now().isoformat(),
                },
            }
        )
        await manager.broadcast(
            {
                "type": "stats_update",
                "data": await asyncio.to_thread(db_module.get_statistics),
            }
        )
        await manager.broadcast(
            {
                "type": "bins_update",
                "data": await asyncio.to_thread(db_module.get_bin_statuses),
            }
        )

        sim.total_sorted += 1
        sim.stats[detected_class] = sim.stats.get(detected_class, 0) + 1
        await asyncio.sleep(random.uniform(2.0, 4.0))


if __name__ == "__main__":
    simulator = WasteSortingSimulator()
    try:
        asyncio.run(simulator.start())
    except KeyboardInterrupt:
        simulator.stop()
        print("\nSimulator stopped cleanly.")
