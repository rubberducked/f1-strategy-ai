"""
ADK Orchestrator for F1 Strategy AI

This module wires up a multi-agent system powered by Google ADK with three
specialist agents:
  - TelemetryAgent: live car telemetry ingestion and feature extraction
  - WeatherAgent: live weather forecast normalization and risk signals
  - StrategyAgent: pit/tyre/pace decisioning and what-if simulation

All agents inherit from google.adk.agents.Agent and communicate via an
in-memory event bus. The orchestrator exposes a simple interface to start,
stop, and stream composite strategy insights for the frontend.

Requirements (examples)
- google-adk >= 0.1.0  (placeholder name; align with actual package)
- pydantic, asyncio, httpx, numpy, pandas
- Optional: google-generativeai for Gemini API calls

Environment
- GCP project/credentials configured if ADK needs them
- GEMINI_API_KEY for Gemini usage
"""
from __future__ import annotations

import asyncio
import json
import os
import time
from dataclasses import dataclass
from typing import Any, AsyncIterator, Dict, List, Optional

try:
    # Placeholder import path; replace with the actual ADK package path in your codebase
    from google.adk.agents import Agent
    from google.adk.events import Event, EventBus
except Exception as e:
    # Lightweight shims to enable local dev without ADK
    class Event(dict):
        pass

    class EventBus:
        def __init__(self):
            self._subs: Dict[str, List] = {}

        def publish(self, topic: str, payload: Dict[str, Any]):
            for cb in self._subs.get(topic, []):
                cb(Event({"topic": topic, "payload": payload, "ts": time.time()}))

        def subscribe(self, topic: str, callback):
            self._subs.setdefault(topic, []).append(callback)

    class Agent:
        def __init__(self, name: str, bus: EventBus):
            self.name = name
            self.bus = bus
            self._task: Optional[asyncio.Task] = None

        async def start(self):
            pass

        async def stop(self):
            if self._task and not self._task.done():
                self._task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._task

import contextlib
import random

# ----------------------------- Data Models -----------------------------
@dataclass
class TelemetrySample:
    car_id: str
    lap: int
    sector_times: List[float]
    speed: float
    tyre_compound: str
    tyre_wear_pct: float
    fuel_kg: float
    position: int

@dataclass
class WeatherSample:
    temp_c: float
    track_temp_c: float
    rain_prob: float
    wind_kph: float

@dataclass
class StrategyInsight:
    recommended_pit_in_laps: Optional[int]
    target_compound: Optional[str]
    pace_delta_s: float
    risk_rain: float
    confidence: float

# ----------------------------- Agents -----------------------------
class TelemetryAgent(Agent):
    """Ingests/streams live telemetry and emits normalized features."""

    def __init__(self, bus: EventBus, source_url: Optional[str] = None):
        super().__init__(name="telemetry", bus=bus)
        self.source_url = source_url
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        await super().stop()

    async def _run(self):
        lap = 1
        while self._running:
            # Simulated telemetry; replace with real feed adapter
            sample = TelemetrySample(
                car_id="RD01",
                lap=lap,
                sector_times=[round(random.uniform(25.0, 35.0), 3) for _ in range(3)],
                speed=round(random.uniform(250, 335), 1),
                tyre_compound=random.choice(["SOFT", "MEDIUM", "HARD"]),
                tyre_wear_pct=round(random.uniform(2, 40), 1),
                fuel_kg=round(random.uniform(15, 110), 1),
                position=random.randint(1, 20),
            )
            self.bus.publish("telemetry.sample", sample.__dict__)
            lap += 1
            await asyncio.sleep(1.0)

class WeatherAgent(Agent):
    """Normalizes weather feed and produces risk signals (e.g., rain)."""

    def __init__(self, bus: EventBus, source_url: Optional[str] = None):
        super().__init__(name="weather", bus=bus)
        self.source_url = source_url
        self._running = False

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        await super().stop()

    async def _run(self):
        while self._running:
            sample = WeatherSample(
                temp_c=round(random.uniform(18, 35), 1),
                track_temp_c=round(random.uniform(22, 55), 1),
                rain_prob=round(random.uniform(0, 0.6), 2),
                wind_kph=round(random.uniform(2, 35), 1),
            )
            self.bus.publish("weather.sample", sample.__dict__)
            await asyncio.sleep(5.0)

class StrategyAgent(Agent):
    """Fuses telemetry and weather to produce strategy insights."""

    def __init__(self, bus: EventBus, use_gemini: bool = False):
        super().__init__(name="strategy", bus=bus)
        self.use_gemini = use_gemini
        self._latest_tel: Optional[TelemetrySample] = None
        self._latest_wx: Optional[WeatherSample] = None
        self._running = False
        self._queue: asyncio.Queue[StrategyInsight] = asyncio.Queue()

        bus.subscribe("telemetry.sample", self.on_telemetry)
        bus.subscribe("weather.sample", self.on_weather)

        self._gemini = None
        if use_gemini:
            with contextlib.suppress(Exception):
                import google.generativeai as genai
                api_key = os.getenv("GEMINI_API_KEY")
                if api_key:
                    genai.configure(api_key=api_key)
                    self._gemini = genai.GenerativeModel("gemini-1.5-flash")

    def on_telemetry(self, event: Event):
        payload = event.get("payload", {})
        self._latest_tel = TelemetrySample(**payload)

    def on_weather(self, event: Event):
        payload = event.get("payload", {})
        self._latest_wx = WeatherSample(**payload)

    async def start(self):
        self._running = True
        self._task = asyncio.create_task(self._run())

    async def stop(self):
        self._running = False
        await super().stop()

    async def _run(self):
        while self._running:
            if self._latest_tel and self._latest_wx:
                insight = await self._compute_insight(self._latest_tel, self._latest_wx)
                await self._queue.put(insight)
                self.bus.publish("strategy.insight", dataclass_to_dict(insight))
            await asyncio.sleep(2.0)

    async def _compute_insight(self, tel: TelemetrySample, wx: WeatherSample) -> StrategyInsight:
        # Simple heuristics; replace with ML/optimization logic
        wear = tel.tyre_wear_pct
        rain = wx.rain_prob
        pace_delta = max(0.0, (wear - 10) * 0.05) + rain * 0.2
        recommend_in = None
        target_compound = None

        if wear > 35 or (rain > 0.45 and tel.tyre_compound in ("SOFT", "MEDIUM")):
            recommend_in = random.randint(1, 3)
            target_compound = "INTERS" if rain > 0.5 else ("HARD" if tel.tyre_compound != "HARD" else "MEDIUM")

        confidence = 0.6 + (0.4 - min(0.4, abs(0.3 - rain))) - min(0.3, wear / 100)
        confidence = max(0.1, min(0.95, confidence))

        # Optional Gemini reasoning to enrich explanations or validate decisions
        if self._gemini:
            try:
                prompt = (
                    "You are an F1 race strategist. Given telemetry and weather, "
                    "suggest pit timing and tyre compound briefly.\n"
                    f"Telemetry: {tel.__dict__}\nWeather: {wx.__dict__}"
                )
                _ = await _maybe_async_call(self._gemini.generate_content, prompt)
                # Response could be appended to insight in future (e.g., explanation)
            except Exception:
                pass

        return StrategyInsight(
            recommended_pit_in_laps=recommend_in,
            target_compound=target_compound,
            pace_delta_s=round(pace_delta, 3),
            risk_rain=rain,
            confidence=round(confidence, 2),
        )

    async def stream_insights(self) -> AsyncIterator[StrategyInsight]:
        while True:
            item = await self._queue.get()
            yield item

# ----------------------------- Orchestrator -----------------------------
class ADKOrchestrator:
    """Coordinates the three agents and provides a unified interface."""

    def __init__(self, use_gemini: bool = False, telemetry_url: Optional[str] = None, weather_url: Optional[str] = None):
        self.bus = EventBus()
        self.telemetry = TelemetryAgent(self.bus, telemetry_url)
        self.weather = WeatherAgent(self.bus, weather_url)
        self.strategy = StrategyAgent(self.bus, use_gemini=use_gemini)
        self._started = False

    async def start(self):
        if self._started:
            return
        await asyncio.gather(
            self.telemetry.start(),
            self.weather.start(),
            self.strategy.start(),
        )
        self._started = True

    async def stop(self):
        if not self._started:
            return
        await asyncio.gather(
            self.telemetry.stop(),
            self.weather.stop(),
            self.strategy.stop(),
        )
        self._started = False

    async def insights_stream(self) -> AsyncIterator[Dict[str, Any]]:
        async for insight in self.strategy.stream_insights():
            yield dataclass_to_dict(insight)

# ----------------------------- Utilities -----------------------------
async def _maybe_async_call(fn, *args, **kwargs):
    res = fn(*args, **kwargs)
    if asyncio.iscoroutine(res):
        return await res
    return res

def dataclass_to_dict(obj: Any) -> Dict[str, Any]:
    if hasattr(obj, "__dict__"):
        return {k: dataclass_to_dict(v) for k, v in obj.__dict__.items()}
    if isinstance(obj, list):
        return [dataclass_to_dict(i) for i in obj]
    return obj

# ----------------------------- CLI demo -----------------------------
async def _demo():
    orch = ADKOrchestrator(use_gemini=bool(os.getenv("GEMINI_API_KEY")))
    await orch.start()
    try:
        async for item in orch.insights_stream():
            print(json.dumps(item))
    except KeyboardInterrupt:
        pass
    finally:
        await orch.stop()

if __name__ == "__main__":
    asyncio.run(_demo())
