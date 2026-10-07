import httpx
import asyncio


async def call():
    async with httpx.AsyncClient() as client:
        response = await client.request(
            url="https://api.apilayer.net/aviationstack/v1/flights?access_key=13db327d5cacb67e35e265a7f307129a&limit=50",
            method="GET",
        )
        response.raise_for_status()
        print(response.text)


asyncio.run(call())
