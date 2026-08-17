from __future__ import annotations

import json
import re
from urllib.parse import quote
from urllib.request import Request, urlopen


_CITY = re.compile(r"^[^\x00-\x1f\x7f]{1,100}$")
_WHEN = {"today", "tomorrow"}


def _weather_url(city: str) -> str:
    return f"https://wttr.in/{quote(city, safe='')}?format=j1"


def _read_payload(city: str) -> dict:
    request = Request(
        _weather_url(city),
        headers={"Accept": "application/json", "User-Agent": "Misha/0.1"},
        method="GET",
    )
    with urlopen(request, timeout=10) as response:
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise ValueError("weather response exceeded the size limit")
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("weather response was not an object")
    return payload


def _first_text(value) -> str:
    if isinstance(value, list) and value and isinstance(value[0], dict):
        return str(value[0].get("value", "")).strip()
    return ""


def _format_weather(city: str, when: str, payload: dict) -> str:
    if when == "today":
        current = payload.get("current_condition")
        if not isinstance(current, list) or not current or not isinstance(current[0], dict):
            raise ValueError("current weather is missing")
        item = current[0]
        temperature = str(item.get("temp_C", "?")).strip()
        feels = str(item.get("FeelsLikeC", "?")).strip()
        description = _first_text(item.get("weatherDesc")) or "conditions unavailable"
        humidity = str(item.get("humidity", "?")).strip()
        return (
            f"Weather for {city}: {description}, {temperature}°C "
            f"(feels like {feels}°C), humidity {humidity}%."
        )

    forecasts = payload.get("weather")
    if not isinstance(forecasts, list) or len(forecasts) < 2 or not isinstance(forecasts[1], dict):
        raise ValueError("tomorrow's forecast is missing")
    item = forecasts[1]
    minimum = str(item.get("mintempC", "?")).strip()
    maximum = str(item.get("maxtempC", "?")).strip()
    hourly = item.get("hourly")
    description = "conditions unavailable"
    if isinstance(hourly, list) and hourly:
        middle = hourly[min(4, len(hourly) - 1)]
        if isinstance(middle, dict):
            description = _first_text(middle.get("weatherDesc")) or description
    return f"Tomorrow in {city}: {description}, {minimum}–{maximum}°C."


def weather_action(parameters: dict, player=None, session_memory=None) -> str:
    city = str(parameters.get("city", "")).strip()
    when = str(parameters.get("time", "today") or "today").strip().casefold()
    if not city or not _CITY.fullmatch(city):
        message = "The city is missing or invalid for the weather report."
        _log(message, player)
        return message
    if when not in _WHEN:
        message = "Weather time must be today or tomorrow."
        _log(message, player)
        return message

    try:
        message = _format_weather(city, when, _read_payload(city))
    except Exception:
        message = "Weather data is temporarily unavailable."
    _log(message, player)

    if session_memory and not message.endswith("unavailable."):
        try:
            session_memory.set_last_search(
                query=f"weather in {city} {when}", response=message
            )
        except Exception:
            pass
    return message


def _log(message: str, player=None) -> None:
    print(f"[Weather] {message}")
    if player:
        try:
            player.write_log(f"MISHA: {message}")
        except Exception:
            pass
