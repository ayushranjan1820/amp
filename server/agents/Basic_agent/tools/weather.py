"""Weather tool for the Langchain agent."""

import requests
from langchain_core.tools import tool


@tool
def get_weather(location: str) -> str:
    """Get weather information for a location.
    
    Args:
        location: The location to get weather for
        
    Returns:
        Weather information as string
    """
    try:
        # Using Open-Meteo API (free, no API key needed)
        response = requests.get(
            f"https://geocoding-api.open-meteo.com/v1/search",
            params={"name": location, "count": 1, "language": "en", "format": "json"}
        )
        
        if response.status_code != 200 or not response.json().get("results"):
            return f"Could not find location: {location}"
        
        location_data = response.json()["results"][0]
        lat, lon = location_data["latitude"], location_data["longitude"]
        
        # Get weather data
        weather_response = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": lat,
                "longitude": lon,
                "current": "temperature_2m,weather_code,wind_speed_10m",
                "timezone": "auto"
            }
        )
        
        if weather_response.status_code == 200:
            weather = weather_response.json()["current"]
            return f"Weather in {location}: Temperature {weather['temperature_2m']}°C, Wind Speed {weather['wind_speed_10m']} km/h"
        
        return "Could not fetch weather data"
    except Exception as e:
        return f"Error fetching weather: {str(e)}"
