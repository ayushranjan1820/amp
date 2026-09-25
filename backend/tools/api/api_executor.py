import httpx
import json
from typing import Any
from tools.tool_config import ApiToolConfig, ApiParamLocation, HTTPMethod
from tools.api.url_validator import ApiValidator
from utils.logger import get_logger
import os

logger = get_logger(__name__)


class ApiToolExecutor:
    """
    Executed HTTP/HTTPS requests based on ApiToolConfig
    """

    def __init__(self, validator: ApiValidator):
        self._validator = validator

    async def execute(self, config: ApiToolConfig, arguments: dict[str, Any]):

        url = config.url

        # validate the API/URL
        self._validator.validate(url)

        # prepare the HTTP request
        query_params = self._extract_parameters(
            config, arguments, ApiParamLocation.QUERY
        )

        path_params = self._extract_parameters(config, arguments, ApiParamLocation.PATH)

        body_params = self._extract_parameters(config, arguments, ApiParamLocation.BODY)

        url = self._replace_path_parameters(url, path_params)

        request_kwargs: dict[str, Any] = {
            "method": config.method.value,
            "url": url,
            "headers": config.headers,
            "params": {**config.query_params, **query_params},
            "timeout": config.timeout_seconds,
        }
        logger.debug(f"Request kwargs: {request_kwargs}")

        if (
            config.method in [HTTPMethod.POST, HTTPMethod.PUT, HTTPMethod.PATCH]
            and body_params
        ):
            request_kwargs["json"] = body_params

        # execute the request
        async with httpx.AsyncClient() as client:
            try:
                response = await client.request(**request_kwargs)

                response.raise_for_status()
                logger.debug(f"Response: {response.text}")
            except httpx.TimeoutException as e:
                logger.error(f"TimeoutException: {e}")
                return self._format_http_error(e)
            except httpx.HTTPStatusError as e:
                logger.error(f"HTTPStatusError: {e}")
                return self._format_http_error(e)
            except httpx.RequestError as e:
                logger.error(f"RequestError: {e}")
                return f"Request error: {e}"
            return self._format_response(response)

    @staticmethod
    def _extract_parameters(
        config: ApiToolConfig, arguments: dict[str, Any], location: ApiParamLocation
    ):
        allowed_names = {
            param.name for param in config.parameters if param.location == location
        }
        return {key: value for key, value in arguments.items() if key in allowed_names}

    @staticmethod
    def _replace_path_parameters(url: str, path_params: dict[str, Any]):
        for name, value in path_params.items():
            placeholder = f"{name}"

            if placeholder not in url:
                continue
            url = url.replace(placeholder, str(value)).replace("{", "").replace("}", "")
        return url

    @staticmethod
    def _format_response(response: httpx.Response) -> str:

        content_type = response.headers.get(
            "content-type",
            "",
        ).lower()

        if "application/json" in content_type:

            try:
                data = response.json()

                result = json.dumps(
                    data,
                    ensure_ascii=False,
                )

            except ValueError:
                result = response.text

        else:
            result = response.text

        return result

    @staticmethod
    def _format_http_error(
        error: httpx.HTTPStatusError,
    ) -> str:

        response = error.response

        return (
            f"API request returned HTTP "
            f"{response.status_code}. "
            f"Response: {response.text[:500]}"
        )
